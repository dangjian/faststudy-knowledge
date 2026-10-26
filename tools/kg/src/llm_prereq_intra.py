#!/usr/bin/env python3
"""llm_prereq_intra.py — LLM 抽取章内 prerequisite（先修依赖）。

kg:infer 已建立"章节首概念链"的跨章 prerequisite 骨架，但章内概念未被排序。
本脚本按章调用 LLM，在章内概念（按节序排列）间补充确凿的先修依赖边，使先修链更细。
DAG 无环检测保全局无环。

用法:
  python llm_prereq_intra.py [--chapter BSDU-8-1-Math-C2] [--root <knowledge>] [--workers 5] [--dry]
"""
import os, sys, json, time, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from openai import OpenAI
from llm_relations_hierarchy import make_client, _reasoning_kw, extract_json

HERE = Path(__file__).resolve()
ROOT_DEFAULT = HERE.parents[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chapter', help='只处理某章（试跑）')
    ap.add_argument('--root', default=str(ROOT_DEFAULT))
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--min-concepts', type=int, default=2)
    args = ap.parse_args()

    client, model = make_client()
    root = Path(args.root)
    data = json.load(open(root / 'dist' / 'graph.json', encoding='utf-8'))
    nodes = data['nodes']; edges = data['edges']

    # chapter -> concepts(ordered by section order)
    sec_order = {n['id']: n.get('order', 0) for n in nodes if n['type'] == 'Section'}
    sec_chap = {n['id']: n.get('chapterId') for n in nodes if n['type'] == 'Section'}
    chap_title = {n['id']: n.get('title') for n in nodes if n['type'] == 'Chapter'}
    tb_subject = {n['id']: n.get('subject') for n in nodes if n['type'] == 'Textbook'}
    sec_textbook = {n['id']: n.get('textbookId') for n in nodes if n['type'] == 'Section'}

    chap_concepts = {}  # chapterId -> list of (order, cid, title)
    for e in edges:
        if e['type'] != 'covered_by':
            continue
        cid, sid = e['from'], e['to']
        if sec_chap.get(sid) is None:
            continue
        cnode = next((n for n in nodes if n['id'] == cid), None)
        if not cnode or cnode['type'] != 'Concept':
            continue
        chap_concepts.setdefault(sec_chap[sid], []).append((sec_order.get(sid, 0), cid, cnode.get('title', '')))

    valid_ids = set(n['id'] for n in nodes)

    # 现有 prerequisite 邻接（DAG）
    adj = {}
    for e in edges:
        if e['type'] == 'prerequisite':
            adj.setdefault(e['from'], set()).add(e['to'])
    def reaches(s, t):
        seen = set(); stack = [s]
        while stack:
            n = stack.pop()
            if n == t: return True
            if n in seen: continue
            seen.add(n)
            for m in adj.get(n, ()): stack.append(m)
        return False

    SYSTEM = "你是初中学科知识图谱构建助手。给定某章按教学顺序排列的概念，判断其中确凿的先修依赖关系。只输出 JSON，不要解释。"
    new_edges = []
    stats = {'chapters': 0, 'pre': 0, 'bad': 0, 'cycle': 0}

    chaps = [args.chapter] if args.chapter else sorted(chap_concepts.keys())
    for ch in chaps:
        clist = sorted(chap_concepts.get(ch, []))
        clist = [c for _, c in [(o, (cid, t)) for o, cid, t in clist]]
        if len(clist) < args.min_concepts:
            continue
        subject = tb_subject.get(sec_textbook.get(next((s for s in sec_chap if sec_chap[s] == ch), None), ''), '')
        clist_ids = [cid for cid, _ in clist]
        id_index = {str(i + 1): cid for i, cid in enumerate(clist_ids)}
        title_map = {t: cid for cid, t in clist}
        lines = "\n".join(f"{i+1}. [{cid}] {t}" for i, (cid, t) in enumerate(clist))
        user = (
            f"章节：{chap_title.get(ch, ch)}（学科：{subject}）\n"
            f"以下为该章按教学顺序的概念（编号. [id] 标题）：\n{lines}\n\n"
            "请判断其中存在明确【学习先后依赖】的概念对（必须先学 A 才能理解/学会 B），输出 JSON：\n"
            '{"prerequisite": [["A_id", "B_id"], ...]}\n'
            "规则：A 是 B 的先修（学完 A 才便于学 B）。仅输出确凿的依赖，不要反向、不要循环。"
            "两端请使用列表中给出的完整 id（方括号里的字符串，如 concept:数学:xxx）；也可只用编号（如 \"1\"）。"
        )

        def resolve(x):
            if x in valid_ids:
                return x
            if x in id_index:
                return id_index[x]
            if x in title_map:
                return title_map[x]
            for cid in clist_ids:
                if x and x in cid:
                    return cid
            return None
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
        for pair in (res.get('prerequisite') or []):
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                a, b = resolve(str(pair[0])), resolve(str(pair[1]))
                if a is None or b is None or a == b:
                    stats['bad'] += 1; continue
                if reaches(b, a):
                    stats['cycle'] += 1; continue
                adj.setdefault(a, set()).add(b)
                new_edges.append((a, b)); stats['pre'] += 1

    if args.dry:
        print("[dry] 完成"); return

    # 合并进 prerequisite.yaml
    relf = root / 'graph' / 'relations' / 'prerequisite.yaml'
    existing = yaml.safe_load(relf.read_text(encoding='utf-8')) or []
    preset = set((e['from'], e['to']) for e in existing)
    added = 0
    for a, b in new_edges:
        if (a, b) in preset:
            continue
        existing.append({"from": a, "to": b}); preset.add((a, b)); added += 1
    relf.write_text(
        "# 关系：先修依赖 (prerequisite, DAG 无环)\n"
        "# Concept -> Concept。跨章骨架来自 infer_relations.ts；章内细化来自 llm_prereq_intra.py\n" +
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f"prerequisite.yaml 追加章内 {added} 条（原 {len(preset)-added} + 新 {added} = {len(existing)}）")
    print(f"统计: 章={stats['chapters']} 新增={stats['pre']} 非法={stats['bad']} 成环跳过={stats['cycle']}")


if __name__ == '__main__':
    main()
