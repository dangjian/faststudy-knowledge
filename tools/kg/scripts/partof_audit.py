#!/usr/bin/env python3
"""part_of 边审计台账：分批列出待判边，记录判定结果，可随时中断续跑。

用法：
  python3 tools/kg/scripts/partof_audit.py next 100    # 打印下一批待判边
  python3 tools/kg/scripts/partof_audit.py apply       # 把 verdict=wrong 的边移至 related
  python3 tools/kg/scripts/partof_audit.py stat        # 看进度

判定写在 tools/kg/eval/partof-audit.json：
  {"<from>|<to>": "ok" | "wrong:<类型>"}
类型：parallel（同类并列）/ cause（因果后果）/ attribute（属性状态）/ object（对象错位）/ unrelated（无关）

为什么要有台账：全量 4,152 条非含容边，一次判不完。台账保证
① 已判的不重复出现 ② 中断后知道进度 ③ 判定理由可追溯。
"""
import json
import os
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
LEDGER = os.path.join(ROOT, 'tools/kg/eval/partof-audit.json')
PART_OF = os.path.join(ROOT, 'graph/relations/part_of.yaml')
RELATED = os.path.join(ROOT, 'graph/relations/related.yaml')


def load_graph():
    with open(os.path.join(ROOT, 'dist/graph.json'), encoding='utf-8') as f:
        return json.load(f)


def norm(s):
    return (s or '').replace(' ', '').replace('\u3000', '')


def read_edges(path):
    """用 yaml.safe_load 读边。

    为什么不能手工 split(': ')：id 里可能包含 ": " 与撇号，yaml.safe_dump 会把它们
    写成单引号形式（如 'concept:英语:Idiom: to hope that one''s children...'）。
    手工切分会把引号留在值里，导致键与台账对不上、边被静默跳过
    （2026-10-29 审计发现：1 条判错边因此漏降级，还让统计少算 2 条）。
    """
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or []
    return [(e['from'], e['to']) for e in data
            if isinstance(e, dict) and 'from' in e and 'to' in e]


def yaml_edges():
    """直接从 part_of.yaml 读边，而不是读 dist 快照（apply 只改 yaml，dist 要等 build）。"""
    return [{'type': 'part_of', 'from': f, 'to': t} for f, t in read_edges(PART_OF)]


def candidates(g):
    """非「标题含容」的 part_of 边，按 id 排序保证顺序稳定。"""
    by_id = {n['id']: n for n in g['nodes']}
    out = []
    skipped = 0
    for e in yaml_edges():
        c, p = by_id.get(e['from']), by_id.get(e['to'])
        if not c or not p:
            skipped += 1
            continue
        if norm(p.get('title')) and norm(p.get('title')) in norm(c.get('title')):
            continue
        out.append(e)
    if skipped:
        print(f'⚠ {skipped} 条边的端点在 dist 中不存在（多为新增概念未 build），已跳过', file=sys.stderr)
    out.sort(key=lambda x: (x['from'], x['to']))
    return out, by_id


def ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding='utf-8') as f:
            return json.load(f)
    return {}


def cmd_next(n, offset=0):
    g = load_graph()
    cands, by_id = candidates(g)
    done = ledger()
    todo = [e for e in cands if f"{e['from']}|{e['to']}" not in done]
    print(f'非含容边 {len(cands)} | 已判 {len(done)} | 待判 {len(todo)}')
    for e in todo[offset:offset + n]:
        c, p = by_id[e['from']], by_id[e['to']]
        expl = (c.get('explanation') or '').replace('\n', ' ')[:40]
        print(f"{e['from']}\t{e['to']}\t{c.get('title')} ⊂ {p.get('title')}\t{expl}")


def _blocks(lines):
    """把 yaml 的边行切成块（每个 - from: 起一块），以便原样保留未删块。"""
    out, cur = [], []
    for l in lines:
        if l.startswith('- from:') and cur:
            out.append(cur); cur = []
        cur.append(l)
    if cur:
        out.append(cur)
    return out


def _atomic_write(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def cmd_apply():
    """把 verdict 以 wrong 开头的边从 part_of 移到 related（幂等、带去重、原子写）。"""
    done = ledger()
    wrong = {k for k, v in done.items() if v.startswith('wrong')}
    if not wrong:
        print('没有判定为 wrong 的边')
        return

    lines = open(PART_OF, encoding='utf-8').read().split('\n')
    kept, moved = [], []
    for blk in _blocks(lines):
        parsed = yaml.safe_load('\n'.join(blk))
        # 块以 "- from:" 开头，safe_load 返回的是「含一个元素的列表」，不是 dict
        entry = parsed[0] if isinstance(parsed, list) and parsed else parsed
        if isinstance(entry, dict) and f"{entry.get('from')}|{entry.get('to')}" in wrong:
            moved.append((entry['from'], entry['to']))
            continue
        kept.extend(blk)
    if not moved:
        print('没有需要移走的边（part_of 已与台账一致）')
        return

    _atomic_write(PART_OF, '\n'.join(kept))

    # related 是无向图：双向都算已存在，避免写出反向副本（历史遗留 202 对互反）
    existing = set()
    for f, t in read_edges(RELATED):
        existing.add((f, t)); existing.add((t, f))
    add = [(f, t) for f, t in moved if (f, t) not in existing]
    dup = len(moved) - len(add)

    rel = open(RELATED, encoding='utf-8').read()
    if rel and not rel.endswith('\n'):
        rel += '\n'
    # 用 safe_dump 而不是 f-string 裸拼：id 里可能含 ": " 与撇号，
    # 裸拼会写出 mapping values are not allowed here（2026-10-29 实际踩到过）
    if add:
        rel += yaml.safe_dump([{'from': f, 'to': t} for f, t in add],
                              allow_unicode=True, sort_keys=False, default_flow_style=False)
    _atomic_write(RELATED, rel)
    msg = f'part_of 移除 {len(moved)} 条，related 追加 {len(add)} 条'
    if dup:
        msg += f'（{dup} 条已存在，跳过）'
    print(msg)


def cmd_stat():
    g = load_graph()
    cands, _ = candidates(g)
    done = ledger()
    live = {f"{f}|{t}" for f, t in read_edges(PART_OF)}
    wrong = sum(1 for v in done.values() if v.startswith('wrong'))
    todo = sum(1 for e in cands if f"{e['from']}|{e['to']}" not in done)
    judged_live = [v for k, v in done.items() if k in live]
    wrong_live = sum(1 for v in judged_live if v.startswith('wrong'))
    print(f'非含容边 {len(cands)} | 台账 {len(done)} 条（含已移走的边）'
          f' | 判错 {wrong} | 待判 {todo}')
    if judged_live:
        print(f'当前 part_of 精度 {(len(judged_live) - wrong_live) / len(judged_live) * 100:.1f}%'
              f'（已判且仍在 part_of 的 {len(judged_live)} 条）')
    missed = [k for k, v in done.items() if v.startswith('wrong') and k in live]
    if missed:
        print(f'⚠ {len(missed)} 条判错边仍在 part_of（未降级）：')
        for k in missed[:5]:
            print('   ', k)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stat'
    if cmd == 'next':
        cmd_next(int(sys.argv[2]) if len(sys.argv) > 2 else 50,
                 int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    elif cmd == 'apply':
        cmd_apply()
    else:
        cmd_stat()
