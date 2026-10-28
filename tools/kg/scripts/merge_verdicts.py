#!/usr/bin/env python3
"""把 agent 回传的判定合并进台账，再统一 apply。

用法：
  python3 tools/kg/scripts/merge_verdicts.py verdicts.tsv [--apply]

verdicts.tsv 每行：from_id<TAB>to_id<TAB>ok|wrong:<类型>
类型：parallel / cause / attribute / object / reverse / unrelated

为什么单独成一个脚本：并行判定时每个 agent 回传一份 TSV，
合并要校验「这条边其实还在 part_of 吗」，否则会把已移走的边记进台账，
导致 stat 的精度被虚高的样本污染。校验不通过的边会单独列出。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
LEDGER = os.path.join(ROOT, 'tools/kg/eval/partof-audit.json')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    do_apply = '--apply' in sys.argv

    with open(os.path.join(ROOT, 'dist/graph.json'), encoding='utf-8') as f:
        g = json.load(f)
    alive = {f"{e['from']}|{e['to']}" for e in g['edges'] if e['type'] == 'part_of'}
    with open(LEDGER, encoding='utf-8') as f:
        ledger = json.load(f)

    merged = wrong = stale = dup = 0
    bad_lines = []
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 3:
            bad_lines.append(f'{ln}: 字段不足 —— {line[:60]}')
            continue
        a, b, v = parts[0].strip(), parts[1].strip(), parts[2].strip()
        key = f'{a}|{b}'
        if key not in alive:
            stale += 1
            continue
        if key in ledger:
            dup += 1
        ledger[key] = v
        merged += 1
        if v.startswith('wrong'):
            wrong += 1

    with open(LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=0)

    print(f'合并 {merged} 条（判错 {wrong}）| 已判过 {dup} | 边已不存在 {stale} | 坏行 {len(bad_lines)}')
    for b in bad_lines[:5]:
        print('  ', b)

    if do_apply:
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools/kg/scripts/partof_audit.py'), 'apply'],
                       check=True, cwd=ROOT)
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools/kg/scripts/partof_audit.py'), 'stat'],
                       check=True, cwd=ROOT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
