#!/usr/bin/env python3
"""
格式精修第一层（确定性）：section 正文的机械清理。

规则（保守、幂等）：
0. 删出版社水印变体行/拆行首尾粘连（自 strip_page_footer.py 并入）
1. 删页眉/页脚行：出版社行、「学科丨X年级X册」书眉
2. 合并 OCR 断行：行尾中文/数字（非句末标点）且下行以中文开头，
   且下行不是栏目词/序号/标题 → 拼接
3. 裸栏目行加粗：随堂练习/习题N.N/知识技能等栏目名独立成行且无 ** → 加粗
标题/表格/插图区块/【图：…】占位一律原样不动（作为合并边界）。

用法:
  python3 polish_format.py content/七年级/下册/历史/PEP-7-2-History --apply
  python3 polish_format.py content --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

HEADER_PAT = re.compile(
    r'^([数学语文英语物理化学生物地理历史]{1,5}|道德与法治)\s*[丨|｜]\s*(七|八|九)年级(上|下|全一)册\s*$|'
    r'^[^，。]{0,12}出版社\s*$|'
    r'^第[一二三四五六七八九十]+[章单元][丨|].{0,20}$|'
    r'^\d{1,3}\s*[语言数物化生史地法]{1,2}.+册.{0,25}(仅供|未经授权|个人学习).{0,20}$'
)
# 0) 出版社水印变体（自 strip_page_footer.py 并入，2026-10-15 统一：RapidOCR 美术字误读族）
WM = r'人民[\s為敎0-9]{0,2}[育龍龙府加杂敎教]{0,2}[\s]?出[\s版颇殿直尔]{0,2}社'
WM_STANDALONE = re.compile(r'^\s*(?:Page\s+\d{1,3}\s*)?' + WM + r'\s*(?:\d{1,3})?\s*$')
WM_PREFIX = re.compile(r'^(' + WM + r')(?=\S)')
WM_SUFFIX = re.compile(r'(?<=\S)(' + WM + r')\s*$')

BARE_COLUMN = re.compile(
    r'^(随堂练习|习题\s*[\d\.]+|复习题|知识技能|数学理解|问题解决|联系拓广|回顾与思考|'
    r'读一读|想一想|做一做|议一议)\s*[:：]?$'
)
LIST_START = re.compile(r'^(\d+[\.、]|（\d+）|\(\d+\)|[①②③④⑤⑥⑦⑧⑨⑩]|图\s*[\d\-\.]+|第\s*\d+\s*题)')
SENT_END = re.compile(r'[。！？；：…”"）)\]】]$')


def clean_lines(lines):
    """原位行处理：marker 行（标题/表格/插图区）作为合并边界，只处理 prose 行。"""
    out = list(lines)
    n_header = n_merge = n_bold = 0

    # 1) 删页眉行（插图区块内除外）
    keep = []
    in_fig = False
    for l in out:
        if l.startswith('#'):
            in_fig = (l.strip() == '## 插图')
            keep.append(True)
        elif in_fig or l.startswith('|'):
            keep.append(True)
        else:
            if l and WM_STANDALONE.match(l):
                keep.append(False)
                n_header += 1
            elif l and WM_PREFIX.search(l) and len(l) - len(WM_PREFIX.search(l).group(0)) > 10:
                out[i] = WM_PREFIX.sub('', l, count=1)
                keep.append(True)
                n_header += 1
            elif l and WM_SUFFIX.search(l) and len(l) - len(WM_SUFFIX.search(l).group(1)) > 10:
                out[i] = WM_SUFFIX.sub('', l, count=1)
                keep.append(True)
                n_header += 1
            elif l and HEADER_PAT.match(l):
                keep.append(False)
                n_header += 1
            else:
                keep.append(True)
    if n_header:
        out = [l for i, l in enumerate(out) if keep[i]]

    # 2) 裸栏目行加粗（原位改写）
    in_fig = False
    for i, l in enumerate(out):
        if l.startswith('#'):
            in_fig = (l.strip() == '## 插图')
            continue
        if in_fig or l.startswith('|') or not l:
            continue
        if BARE_COLUMN.match(l) and not l.startswith('**'):
            out[i] = f'**{l}**'
            n_bold += 1

    # 3) 断行合并：从后往前，(i, i+1) 合并不影响前面索引
    def figzone(j, arr):
        in_f = False
        for k in range(j + 1):
            if arr[k].startswith('#'):
                in_f = (arr[k].strip() == '## 插图')
        return in_f

    def mergeable(a, b):
        if not a or not b:
            return False
        if a.startswith(('#', '|', '【图', '**')) or b.startswith(('#', '|', '【图', '**')):
            return False
        if not re.search(r'[\u4e00-\u9fff\d]$', a):
            return False
        if SENT_END.search(a):
            return False
        if not re.match(r'^[\u4e00-\u9fff]', b):
            return False
        if LIST_START.match(b) or BARE_COLUMN.match(b):
            return False
        return len(a) > 6

    i = len(out) - 2
    while i >= 0:
        if not figzone(i, out) and not figzone(i + 1, out):
            a, b = out[i], out[i + 1]
            if mergeable(a, b):
                out[i] = a + b
                del out[i + 1]
                n_merge += 1
        i -= 1
    return out, n_header, n_merge, n_bold


def polish_file(path, apply):
    text = path.read_text(encoding='utf-8')
    m = re.match(r'^(---\n.*?\n---\n)', text, flags=re.S)
    fm = m.group(1) if m else ''
    body = text[len(fm):]
    merged, n_header, n_merge, n_bold = clean_lines(body.split('\n'))
    new_body = '\n'.join(merged)
    changed = new_body != body
    if apply and changed:
        path.write_text(fm + new_body, encoding='utf-8')
    return {'file': str(path.relative_to(REPO / 'knowledge')),
            'changed': changed, 'header': n_header, 'merge': n_merge, 'bold': n_bold}


def collect(root):
    if (root / 'chapters').is_dir():
        return sorted((root / 'chapters').glob('*/sections/S*.md'))
    if root.name == 'content':
        return sorted(root.glob('*/*/*/*/chapters/*/sections/S*.md'))
    return sorted(root.glob('chapters/*/sections/S*.md')) if root.is_dir() else [root]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', type=Path)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    root = args.path if args.path.is_absolute() else REPO / 'knowledge' / args.path

    files = collect(root)
    tot_h = tot_m = tot_b = 0
    n_changed = 0
    for f in files:
        r = polish_file(f, apply=args.apply)
        tot_h += r['header']; tot_m += r['merge']; tot_b += r['bold']
        n_changed += r['changed']
        if r['changed'] and (r['header'] or r['merge'] or r['bold']):
            print(f"  [{r['file'].split('content/')[1]}] 页眉-{r['header']} 合并{r['merge']} 加粗{r['bold']}")
    print(f"\nfiles: {len(files)}, changed: {n_changed}, "
          f"header-removed: {tot_h}, merges: {tot_m}, bolded: {tot_b}, "
          f"mode: {'APPLY' if args.apply else 'dry-run'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
