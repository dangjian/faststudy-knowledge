#!/usr/bin/env python3
"""llm_relations_hierarchy.py — LLM 语义抽取 part_of(层级) + 跨章 related。

与 kg:infer 的确定性推导互补：
  - kg:infer 负责 demonstrates / 同章 related / 章节链 prerequisite（无需 LLM）
  - 本脚本负责需要语义判断的两类：
      * part_of   : Concept -> Concept（is-a / 隶属 / 子主题），当前 0 实例
      * related_cross : 分属不同章节的强相关 Concept 对（解锁课程级关联）

按学科分批，每批一次 LLM 调用同时产出两类边，最省调用。
用法:
  python llm_relations_hierarchy.py [--subject 数学] [--root <knowledge>] [--workers 5] [--dry]
"""
import os, sys, json, re, time, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

HERE = Path(__file__).resolve()
ROOT_DEFAULT = HERE.parents[3]  # knowledge


def load_dotenv_keys() -> None:
    for path in (HERE.parents[3] / '.env', Path.cwd() / '.env'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def make_client() -> tuple[OpenAI, str]:
    """凭据统一走 AI_*（任意 OpenAI 兼容服务）：AI_BASE_URL 缺省=OpenAI 官方端点，AI_MODEL 必填。"""
    load_dotenv_keys()
    if not os.environ.get('AI_API_KEY'):
        raise SystemExit('缺少 AI_API_KEY（另可配 AI_BASE_URL 指向兼容服务端点、AI_MODEL 指定模型）')
    if not os.environ.get('AI_MODEL'):
        raise SystemExit('缺少 AI_MODEL')
    return (
        OpenAI(
            api_key=os.environ['AI_API_KEY'],
            base_url=os.environ.get('AI_BASE_URL') or None,
        ),
        os.environ['AI_MODEL'],
    )
def _reasoning_kw(model: str) -> dict:
    eff = os.environ.get('AI_REASONING_EFFORT') or os.environ.get('AI_REASONING_EFFORT')
    # none = 关推理,此时不传该参数(传字面量 'none' 会被服务端当非法值)
    if eff and eff != 'none':
        return {'reasoning_effort': eff}
    return {}


def extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    # 去掉 markdown 代码围栏 ```json ... ```
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\n', '', t)
        t = re.sub(r'\n```$', '', t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S) or re.search(r'\[.*\]', t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


SYSTEM = (
    "你是初中学科知识图谱构建助手。给定同一学科的一组概念（每项含 id、标题、所属章节），"
    "你需要严谨地判断两类关系。只输出 JSON，不要任何解释或 markdown。"
)

USER_TMPL = """学科：{subject}
以下是该学科的一组概念，每项格式为 [id] 标题 @章节：

{lines}

请严格基于学科知识判断，输出 JSON：
{{
  "part_of": [["具体概念id", "更概括概念id"], ...],
  "related_cross": [["id_a", "id_b"], ...]
}}

规则：
1. part_of：表示"具体概念 属于 / 是 / 隶属于 概括概念的一种或一部分"（如 二次函数 属于 函数；等腰三角形 属于 三角形；细胞 属于 生物体结构层次）。
   - 仅当确凿无疑时输出，避免过度联想。
   - 概括概念必须出现在上面的概念列表中（用其 id）。
   - 不要输出循环（A 属于 B 且 B 属于 A）。
2. related_cross：两个概念分属【不同章节】（@后的章节标识不同）且内容强相关（同知识族、互为应用、对比概念、前后铺垫）。
   - 同章节的不要输出（已由其他流程覆盖）。
   - 两端 id 必须都在列表中。
3. 所有 id 必须原样使用列表中给出的 id，不得改写或自造。
"""


def build_chapter_map(nodes):
    sec2chap = {}
    tb2grade = {}
    for n in nodes:
        if n['type'] == 'Section':
            sec2chap[n['id']] = n.get('chapterId') or n['id'].rsplit('-S', 1)[0]
        elif n['type'] == 'Textbook':
            tb2grade[n['id']] = n.get('grade')
    return sec2chap, tb2grade


def chapter_label_of(concept_id, covered, sec2chap):
    secs = covered.get(concept_id)
    if secs:
        return sec2chap.get(secs[0], secs[0])
    return '?'


def call_llm(client, model, subject, window):
    lines = "\n".join(f"[{c['id']}] {c['title']} @{c['chap']}" for c in window)
    user = USER_TMPL.format(subject=subject, lines=lines)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.1,
                **_reasoning_kw(model),
            )
            text = resp.choices[0].message.content or ""
            data = extract_json(text)
            if data and isinstance(data, dict):
                return data
        except Exception as e:
            print(f"    [retry {attempt+1}] {e}")
            time.sleep(2 + attempt)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subject', help='只处理某学科（试跑用）')
    ap.add_argument('--root', default=str(ROOT_DEFAULT))
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--window', type=int, default=28)
    ap.add_argument('--step', type=int, default=18)
    args = ap.parse_args()

    client, model = make_client()
    root = Path(args.root)
    dist = root / 'dist' / 'graph.json'
    data = json.load(open(dist, encoding='utf-8'))
    nodes = data['nodes']; edges = data['edges']

    sec2chap, _ = build_chapter_map(nodes)
    covered = {}
    for e in edges:
        if e['type'] == 'covered_by':
            covered.setdefault(e['from'], []).append(e['to'])

    concepts = [n for n in nodes if n['type'] == 'Concept']
    # 给每个概念打章节标签
    for c in concepts:
        c['chap'] = chapter_label_of(c['id'], covered, sec2chap)
    by_subject = {}
    for c in concepts:
        by_subject.setdefault(c.get('subject', '其他'), []).append(c)

    # 合法 id 集合（端点校验）
    valid_ids = set(n['id'] for n in nodes)

    partof_edges = []   # (specific, general)
    related_edges = []  # (a, b)
    stats = {'windows': 0, 'partof': 0, 'related': 0, 'bad_ref': 0}

    subjects = [args.subject] if args.subject else sorted(by_subject.keys())
    for subject in subjects:
        clist = by_subject.get(subject, [])
        if not clist:
            continue
        # 按章节标签排序，使相关概念相邻
        clist = sorted(clist, key=lambda c: c['chap'])
        print(f"\n=== 学科 {subject}: {len(clist)} 概念 ===")
        windows = []
        for i in range(0, max(1, len(clist) - args.window) + 1, args.step):
            windows.append(clist[i:i + args.window])
        if not windows:
            windows = [clist]
        print(f"  分 {len(windows)} 个窗口 (size={args.window}, step={args.step})")

        def work(w):
            return call_llm(client, model, subject, w)

        if args.dry:
            continue
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, w): w for w in windows}
            for fut in as_completed(futs):
                res = fut.result()
                stats['windows'] += 1
                for pair in (res.get('part_of') or []):
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        a, b = pair[0], pair[1]
                        if a in valid_ids and b in valid_ids and a != b:
                            partof_edges.append((a, b))
                        else:
                            stats['bad_ref'] += 1
                for pair in (res.get('related_cross') or []):
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        a, b = pair[0], pair[1]
                        if a in valid_ids and b in valid_ids and a != b:
                            related_edges.append((a, b))
                        else:
                            stats['bad_ref'] += 1
        print(f"  累计 part_of={len(partof_edges)} related_cross={len(related_edges)}")

    if args.dry:
        print("[dry] 完成，未写入"); return

    # ---- part_of DAG 校验（去环）----
    parent = {}  # specific -> general
    adj = {}
    def reaches(s, t):
        seen = set(); stack = [s]
        while stack:
            n = stack.pop()
            if n == t: return True
            if n in seen: continue
            seen.add(n)
            for m in adj.get(n, ()): stack.append(m)
        return False
    clean_partof = []
    for a, b in partof_edges:
        if a in parent: continue  # 已有一条（取首条）
        if reaches(b, a):  # b 已能到达 a -> 加 a->b 成环
            continue
        parent[a] = b
        adj.setdefault(a, set()).add(b)
        clean_partof.append((a, b))
    print(f"\npart_of 去重+去环后: {len(clean_partof)} (原始 {len(partof_edges)}, 丢弃 {len(partof_edges)-len(clean_partof)})")

    # ---- 写 part_of.yaml（当前为空，整体覆盖）----
    rel_dir = root / 'graph' / 'relations'
    import yaml
    pof = rel_dir / 'part_of.yaml'
    pof.write_text(
        "# 关系：隶属 / 层级 (part_of)\n"
        "# 格式: from: <具体 Concept ID>, to: <概括 Concept ID>\n"
        "# 由 tools/kg/src/llm_relations_hierarchy.py 按学科分批 LLM 语义抽取（DAG 无环）\n" +
        yaml.safe_dump([{"from": a, "to": b} for a, b in clean_partof], allow_unicode=True, sort_keys=False),
        encoding='utf-8')
    print(f"已写入 {pof} ({len(clean_partof)} 条)")

    # ---- related_cross 合并进 related.yaml（去重）----
    relf = rel_dir / 'related.yaml'
    existing = yaml.safe_load(relf.read_text(encoding='utf-8')) or []
    relset = set((e['from'], e['to']) for e in existing)
    added = 0
    for a, b in related_edges:
        key = (a, b)
        if key in relset: continue
        # 无向去重：也检查 (b,a)
        if (b, a) in relset: continue
        existing.append({"from": a, "to": b})
        relset.add(key)
        added += 1
    relf.write_text(
        "# 关系：相关关系 (related)\n"
        "# from/to: Concept ID。同章星形来自 infer_relations.ts；跨章部分来自 llm_relations_hierarchy.py\n" +
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f"related.yaml 追加跨章 {added} 条（原 {len(relset)-added} + 新 {added} = {len(existing)}）")

    print(f"\n=== 统计 ===\n窗口:{stats['windows']} part_of:{len(clean_partof)} related_cross新增:{added} 非法引用:{stats['bad_ref']}")


if __name__ == '__main__':
    main()
