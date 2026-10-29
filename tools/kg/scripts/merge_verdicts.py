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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import partof_audit as pa  # noqa: E402  复用 read_edges，保证与 apply 同一口径

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
LEDGER = os.path.join(ROOT, 'tools/kg/eval/partof-audit.json')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    do_apply = '--apply' in sys.argv

    # 必须读 part_of.yaml 而不是 dist/graph.json：apply 只改 yaml，dist 要等 kg:build。
    # 读 dist 会让「边是否还在」恒为真（apply 后未 build 时），把已移走的边判为存活，
    # 判定被错误接受、精度虚高；反向也会把 yaml 新增边误判 stale 丢掉。
    alive = {f'{f}|{t}' for f, t in pa.read_edges(pa.PART_OF)}
    with open(LEDGER, encoding='utf-8') as f:
        ledger = json.load(f)

    VALID = {'ok', 'wrong:parallel', 'wrong:cause', 'wrong:attribute',
             'wrong:object', 'wrong:reverse', 'wrong:unrelated'}
    merged = wrong = stale = dup = 0
    bad_lines, stale_keys = [], []
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 3:
            bad_lines.append(f'{ln}: 字段不足 —— {line[:60]}')
            continue
        a, b, v = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if v not in VALID:
            bad_lines.append(f'{ln}: 非法判定 {v!r}（须为 ok 或 wrong:<类型>）')
            continue
        key = f'{a}|{b}'
        if key not in alive:
            stale += 1
            stale_keys.append(key)
            continue
        if key in ledger:
            dup += 1
        ledger[key] = v
        merged += 1
        if v.startswith('wrong'):
            wrong += 1

    tmp = LEDGER + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=0)
    os.replace(tmp, LEDGER)

    print(f'合并 {merged} 条（判错 {wrong}）| 已判过 {dup} | 边已不存在 {stale} | 坏行 {len(bad_lines)}')
    for b in bad_lines[:5]:
        print('  坏行', b)
    for k in stale_keys[:5]:
        print('  边已不存在', k)
    if len(stale_keys) > 5:
        print(f'  … 另有 {len(stale_keys) - 5} 条边已不存在（明细见上）')

    if do_apply:
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools/kg/scripts/partof_audit.py'), 'apply'],
                       check=True, cwd=ROOT)
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools/kg/scripts/partof_audit.py'), 'stat'],
                       check=True, cwd=ROOT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
