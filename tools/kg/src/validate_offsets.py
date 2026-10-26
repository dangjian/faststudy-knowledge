#!/usr/bin/env python3
"""offset 三处一致性校验器（D6 单一维护点门禁）。

三处配置：
  1. knowledge/content/<书>/index.md 的 imageOffset   ← 唯一真源
  2. knowledge/source_data/<书>/metadata.json         ← 摄入管线（应与 1 一致）
  3. PG textbooks."pageOffset"                        ← 产品端（--pg 时校验，应与 1 一致）

用法（knowledge 仓根）:
  python3 tools/kg/src/validate_offsets.py            # 校验 1 vs 2
  python3 tools/kg/src/validate_offsets.py --pg       # 追加校验 1 vs 3（本地 PG）
不一致时 exit 1 并列出全部差异；修复方式：改 knowledge index.md 后按派生链同步
（metadata 手改 / PG 走 migration），禁止反向单独改派生处。
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def knowledge_offsets() -> dict[str, int]:
    out = {}
    for p in glob.glob(os.path.join(ROOT, 'content', '*', '*', '*', '*', 'index.md')):
        s = open(p, encoding='utf-8').read()
        m = re.search(r'^imageOffset: (\d+)$', s, re.MULTILINE)
        if m:
            out[os.path.basename(os.path.dirname(p))] = int(m.group(1))
    return out


def metadata_offsets() -> dict[str, int]:
    out = {}
    base = os.path.join(ROOT, 'source_data')
    for p in glob.glob(os.path.join(base, '*', 'metadata.json')):
        import json
        m = json.load(open(p, encoding='utf-8'))
        if isinstance(m.get('imageOffset'), int):
            out[os.path.basename(os.path.dirname(p))] = m['imageOffset']
    return out


def pg_offsets() -> dict[str, int]:
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise RuntimeError('未设置 DATABASE_URL 环境变量（--pg 模式需要）')
    r = subprocess.run(
        ['psql', db_url, '-t', '-A', '-F', '|', '-c',
         'SELECT id, "pageOffset" FROM textbooks'],
        capture_output=True, text=True, check=True,
    )
    out = {}
    for line in r.stdout.splitlines():
        if '|' in line:
            k, v = line.split('|', 1)
            out[k] = int(v)
    return out


def main() -> None:
    kg = knowledge_offsets()
    md = metadata_offsets()
    diffs: list[str] = []

    for bid in sorted(kg):
        if bid in md and md[bid] != kg[bid]:
            diffs.append(f'{bid}: knowledge={kg[bid]} vs metadata={md[bid]}')
    for bid in sorted(set(md) - set(kg)):
        diffs.append(f'{bid}: metadata={md[bid]} 但 knowledge 无声明（metadata 多余）')

    if '--pg' in sys.argv:
        pg = pg_offsets()  # fail-loud：连不上库直接报错，不静默降级
        for bid in sorted(kg):
            if bid in pg and pg[bid] != kg[bid]:
                diffs.append(f'{bid}: knowledge={kg[bid]} vs PG={pg[bid]}')

    if diffs:
        print(f'✖ {len(diffs)} 处 offset 不一致（唯一真源=knowledge index.md，按派生链同步）：')
        for d in diffs:
            print(' ', d)
        sys.exit(1)
    print(f'✓ offset 三处一致（knowledge {len(kg)} 本'
          + (f'，PG 对比 {len(pg)} 本' if '--pg' in sys.argv else '') + '）')


if __name__ == '__main__':
    main()
