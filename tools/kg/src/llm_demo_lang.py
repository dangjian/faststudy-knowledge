#!/usr/bin/env python3
"""llm_demo_lang.py — LLM 增强语言类 demonstrates（英语 item -> 概念）。

kg:infer 的 demonstrates 用"中文概念名命中 item 文本"推导，对英语 Word/Phrase/Sentence 几乎失效
（英语词的中文释义很少直接等于学科概念名）。本脚本按英语章节调用 LLM，将内容项链接到其演示/例示的
英语学科概念（如某个句子演示"宾语从句"语法概念），补全 demonstrates 的语言侧覆盖。

用法:
  python llm_demo_lang.py [--chapter PEP-9-0-English-C3] [--root <knowledge>] [--workers 5] [--dry]
"""
import os, json, time, argparse, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from openai import OpenAI
from llm_relations_hierarchy import make_client, _reasoning_kw, extract_json

HERE = Path(__file__).resolve()
ROOT_DEFAULT = HERE.parents[3]
ITEM_TYPES = ('Word', 'Phrase', 'Sentence')


def section_id_from_ref(ref: str):
    m = re.search(r'/([^/]+)/chapters/(C\d+)/sections/(.+?)\.md$', ref or '')
    if not m:
        return None
    sm = re.search(r'S(\d+)', m.group(3))
    if not sm:
        return None
    return f"{m.group(1)}-{m.group(2)}-S{sm.group(1)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chapter', help='只处理某英语章（试跑）')
    ap.add_argument('--root', default=str(ROOT_DEFAULT))
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    client, model = make_client()
    root = Path(args.root)
    data = json.load(open(root / 'dist' / 'graph.json', encoding='utf-8'))
    nodes = data['nodes']; edges = data['edges']

    sec_chap = {n['id']: n.get('chapterId') for n in nodes if n['type'] == 'Section'}
    chap_title = {n['id']: n.get('title') for n in nodes if n['type'] == 'Chapter'}

    # 概念按章
    chap_concepts = {}
    for e in edges:
        if e['type'] == 'covered_by':
            chap_concepts.setdefault(sec_chap.get(e['to']), []).append(e['from'])

    # item 按章
    chap_items = {}
    for n in nodes:
        if n['type'] not in ITEM_TYPES or not n.get('sourceRef'):
            continue
        sid = section_id_from_ref(n['sourceRef'])
        ch = sec_chap.get(sid) if sid else None
        if not ch:
            continue
        o = n
        text = ' '.join(str(o.get(k, '')) for k in ('word', 'meaning', 'en', 'cn', 'english') if o.get(k))
        chap_items.setdefault(ch, []).append((n['id'], text.strip()))

    valid_ids = set(n['id'] for n in nodes)
    SYSTEM = "你是初中英语知识图谱构建助手。给定某单元的英语内容与对应语法/词汇概念，判断哪些内容项演示(例示)了哪些概念。只输出 JSON，不要解释。"

    new_edges = []
    stats = {'chapters': 0, 'demo': 0, 'bad': 0}

    chaps = [args.chapter] if args.chapter else sorted(k for k in chap_concepts if (chap_title.get(k, '').find('English') >= 0 or 'English' in k or '英语' in str(chap_title.get(k, ''))) and k in chap_items)
    for ch in chaps:
        items = chap_items.get(ch, [])
        concepts = chap_concepts.get(ch, [])
        if not items or not concepts:
            continue
        # 限制概念规模，避免超长
        concepts = concepts[:60]
        item_ids = {iid for iid, _ in items[:80]}
        concept_ids = set(concepts)
        id_title = {}
        for iid, t in items[:80]:
            if t:
                id_title[t] = iid
        for cid in concepts:
            id_title.setdefault(next((n.get('title', '') for n in nodes if n['id'] == cid), cid), cid)

        def resolve(x):
            if x in valid_ids:
                return x
            if x in item_ids or x in concept_ids:
                return x
            if x in id_title:
                return id_title[x]
            for cid in list(item_ids) + list(concept_ids):
                if x and x in cid:
                    return cid
            return None

        item_lines = "\n".join(f"[{iid}] {t}" for iid, t in items[:80])
        con_lines = "\n".join(f"[{cid}] {next((n.get('title','') for n in nodes if n['id']==cid), cid)}" for cid in concepts)
        user = (
            f"单元：{chap_title.get(ch, ch)}\n"
            f"英语内容项（词/短语/句子）：\n{item_lines}\n\n"
            f"本单元涉及的英语学科概念（语法/词汇/功能）：\n{con_lines}\n\n"
            "请判断每个内容项【演示/例示】了哪些概念（即该项用来讲解或体现该概念），输出 JSON：\n"
            '{"demonstrates": [["item_id", "concept_id"], ...]}\n'
            "规则：仅当内容项确实在讲解/体现该概念时才连线。两端 id 必须用上面给出的（方括号里的字符串）。一个 item 可连多个概念，也可不连。"
        )
        if args.dry:
            continue
        stats['chapters'] += 1
        res = {}
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"}, temperature=0.1, **_reasoning_kw(model))
                res = extract_json(resp.choices[0].message.content or "") or {}
                break
            except Exception as ex:
                print(f"  [retry {attempt+1}] {ex}"); time.sleep(2 + attempt)
        for pair in (res.get('demonstrates') or []):
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                a, b = resolve(str(pair[0])), resolve(str(pair[1]))
                if a and b and a != b:
                    new_edges.append((a, b)); stats['demo'] += 1
                else:
                    stats['bad'] += 1

    if args.dry:
        print("[dry] 完成"); return

    relf = root / 'graph' / 'relations' / 'demonstrates.yaml'
    existing = yaml.safe_load(relf.read_text(encoding='utf-8')) or []
    dset = set((e['from'], e['to']) for e in existing)
    added = 0
    for a, b in new_edges:
        if (a, b) in dset:
            continue
        existing.append({"from": a, "to": b}); dset.add((a, b)); added += 1
    relf.write_text(
        "# 关系：学习项演示概念 (demonstrates)\n"
        "# from: Item(Word/Phrase/Sentence/Character), to: Concept\n"
        "# 中文侧来自 infer_relations.ts；英语侧来自 llm_demo_lang.py\n" +
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f"demonstrates.yaml 追加英语 {added} 条（原 {len(dset)-added} + 新 {added} = {len(existing)}）")
    print(f"统计: 英语章={stats['chapters']} 新增={stats['demo']} 非法={stats['bad']}")


if __name__ == '__main__':
    main()
