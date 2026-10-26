#!/usr/bin/env python3
"""flatten_scan.py — 交错/压平类缺陷扫描（residual_scan 的盲区补位）

原理：地图注记压平、双栏气泡交错、硬换行碎片在 md 中的共同机械特征是
「无句末标点的短行连跑」（≥5 行连续，每行规范化后 ≤10 字且不以。？！：结尾）。
对每节扫描此类连跑并报告样本。

用法:
  python3 tools/kg/scripts/flatten_scan.py [BookId] [--min-run 5] [--max-len 10] [--json OUT]
不带 BookId 则扫全仓。
"""
import re
import sys
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTENT = ROOT / 'content'

END_PUNCT = ('。', '？', '！', '：', '；', '”', '）')
CJK = re.compile(r'[\u4e00-\u9fff0-9A-Za-z]')


def norm(s: str) -> str:
    return ''.join(CJK.findall(s))


def scan_section(md: pathlib.Path, min_run: int, max_len: int):
    t = md.read_text()
    body = re.sub(r'\A---\n.*?\n---\n', '', t, flags=re.S)
    idx = body.find('\n---\n')
    if idx >= 0:
        body = body[:idx]
    lines = [l.strip() for l in body.splitlines()]
    runs = []
    cur = []
    for l in lines:
        # 豁免：md 列表项（图例/目录等合法列表）、选择题选项行、表格行
        if re.match(r'^[-*•]\s', l) or re.match(r'^[A-F][.、．]', l):
            continue
        if not l or l.startswith('#') or l.startswith('|') or l.startswith('---'):
            if len(cur) >= min_run:
                runs.append(cur)
            cur = []
            continue
        nl = norm(l)
        if 0 < len(nl) <= max_len and not l.endswith(END_PUNCT) and not re.match(r'^\d+[\.、]', l):
            cur.append(l)
        else:
            if len(cur) >= min_run:
                runs.append(cur)
            cur = []
    if len(cur) >= min_run:
        runs.append(cur)
    return runs


def main():
    args = sys.argv[1:]
    min_run, max_len, json_out, book = 5, 10, None, None
    it = iter(range(len(args)))
    i = 0
    while i < len(args):
        if args[i] == '--min-run':
            min_run = int(args[i + 1]); i += 2
        elif args[i] == '--max-len':
            max_len = int(args[i + 1]); i += 2
        elif args[i] == '--json':
            json_out = args[i + 1]; i += 2
        elif not args[i].startswith('--'):
            book = args[i]; i += 1
        else:
            i += 1

    if book:
        secs = sorted(CONTENT.rglob(f'**/{book}/chapters/*/sections/S*.md'))
    else:
        secs = sorted(CONTENT.rglob('chapters/*/sections/S*.md'))

    report = []
    for md in secs:
        runs = scan_section(md, min_run, max_len)
        if runs:
            report.append({
                'sec': str(md.relative_to(CONTENT)),
                'runs': [{'n': len(r), 'head': r[0][:30], 'lines': r[:8]} for r in runs],
            })

    total = sum(sum(x['n'] for x in r['runs']) for r in report)
    for r in sorted(report, key=lambda x: -sum(x['n'] for x in x['runs']))[:40]:
        tot = sum(x['n'] for x in r['runs'])
        print(f"{tot:4d} 行/{len(r['runs'])} 段  {r['sec'].split('chapters/')[-1]}"
              f"  首段: {r['runs'][0]['head']}…")
    print(f"\nsections with runs={len(report)}  total short-line runs={total}")
    if json_out:
        pathlib.Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
