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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
LEDGER = os.path.join(ROOT, 'tools/kg/eval/partof-audit.json')
PART_OF = os.path.join(ROOT, 'graph/relations/part_of.yaml')
RELATED = os.path.join(ROOT, 'graph/relations/related.yaml')


def load_graph():
    with open(os.path.join(ROOT, 'dist/graph.json'), encoding='utf-8') as f:
        return json.load(f)


def norm(s):
    return (s or '').replace(' ', '').replace('\u3000', '')


def yaml_edges():
    """直接从 part_of.yaml 读边，而不是读 dist 快照。

    为什么：apply 只改 yaml，dist 要等 kg:build 才更新。若这里读 dist，
    apply 之后立刻 stat/next 拿到的是旧图，offset 切片会重叠或漏判
    （第 13 轮就因此把「待判」算成了 -44）。
    """
    out = []
    lines = open(os.path.join(ROOT, 'graph/relations/part_of.yaml'), encoding='utf-8').read().split('\n')
    i = 0
    while i < len(lines):
        if lines[i].startswith('- from:') and i + 1 < len(lines) and lines[i + 1].startswith('  to:'):
            out.append({'type': 'part_of',
                        'from': lines[i].split(': ', 1)[1].strip(),
                        'to': lines[i + 1].split(': ', 1)[1].strip()})
            i += 2
            continue
        i += 1
    return out


def candidates(g):
    """非「标题含容」的 part_of 边，按 id 排序保证顺序稳定。"""
    by_id = {n['id']: n for n in g['nodes']}
    out = []
    for e in yaml_edges():
        c, p = by_id.get(e['from']), by_id.get(e['to'])
        if not c or not p:
            continue
        if norm(p.get('title')) and norm(p.get('title')) in norm(c.get('title')):
            continue
        out.append(e)
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


def cmd_apply():
    """把 verdict 以 wrong 开头的边从 part_of 移到 related。"""
    g = load_graph()
    done = ledger()
    wrong = {k for k, v in done.items() if v.startswith('wrong')}
    if not wrong:
        print('没有判定为 wrong 的边')
        return

    lines = open(PART_OF, encoding='utf-8').read().split('\n')
    kept, moved, i = [], [], 0
    while i < len(lines):
        if lines[i].startswith('- from:'):
            frm = lines[i].split(': ', 1)[1].strip()
            to = lines[i + 1].split(': ', 1)[1].strip() if i + 1 < len(lines) and lines[i + 1].startswith('  to:') else ''
            if f"{frm}|{to}" in wrong:
                moved.append((frm, to))
                i += 2
                continue
        kept.append(lines[i])
        i += 1
    open(PART_OF, 'w', encoding='utf-8').write('\n'.join(kept))

    rel = open(RELATED, encoding='utf-8').read()
    if rel and not rel.endswith('\n'):
        rel += '\n'
    rel += ''.join(f'- from: {f}\n  to: {t}\n' for f, t in moved)
    open(RELATED, 'w', encoding='utf-8').write(rel)
    print(f'part_of 移除 {len(moved)} 条，related 追加 {len(moved)} 条')


def cmd_stat():
    g = load_graph()
    cands, _ = candidates(g)
    done = ledger()
    wrong = sum(1 for v in done.values() if v.startswith('wrong'))
    todo = sum(1 for e in cands if f"{e['from']}|{e['to']}" not in done)
    print(f'非含容边 {len(cands)} | 台账 {len(done)} 条（含已移走的边）| 判错 {wrong} | 待判 {todo}')
    if done:
        print(f'样本精度 {(len(done) - wrong) / len(done) * 100:.1f}%')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stat'
    if cmd == 'next':
        cmd_next(int(sys.argv[2]) if len(sys.argv) > 2 else 50,
                 int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    elif cmd == 'apply':
        cmd_apply()
    else:
        cmd_stat()
