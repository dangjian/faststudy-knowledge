#!/usr/bin/env python3
"""小学教材书级 index.md 生成器（spec：小学入图管线 P0.2）。

只写书级 index.md，不碰章节文件。输入：
  - seed JSON（tools/kg/seeds/primary-textbooks.json，摄入输入快照）：书元数据、章 order 与 [startPage, endPage]（D8）
  - chapters/C*/index.md 的 title；sections/S*.md 的 pageRange 与首标题
  - pipeline_toc.json：仅作 G1 交叉校验
门禁 G1–G7 任一不过即退出 1（列全部问题，不做静默修补）。已存在的 index.md 须 --force 才覆盖。

运行（在 knowledge/tools/kg 下）:
  python3 src/gen_book_index.py --root ../.. --seed seeds/primary-textbooks.json \
      --toc-root ../../../source_data [--only PEP-3-1-English] [--check] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from primary_common import (
    chapter_key, first_heading, load_seed, locate_book, read_doc, section_files, section_no,
)


class GateError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__('\n'.join(problems))
        self.problems = problems


def build_book(content_root: Path, book: dict, chapters: list[dict], toc_root: Path) -> tuple[Path, dict]:
    tb = book['id']
    problems: list[str] = []
    book_dir = locate_book(content_root, tb)

    toc = json.loads((toc_root / tb / 'pipeline_toc.json').read_text(encoding='utf-8'))
    if (toc['offset'], toc['totalPages']) != (book['pageOffset'], book['totalPages']):
        problems.append(f"G1 {tb}: seed offset/totalPages=({book['pageOffset']}, {book['totalPages']}) "
                        f"≠ pipeline_toc ({toc['offset']}, {toc['totalPages']})")

    printed_max = book['totalPages'] - book['pageOffset']

    dirs = {d.name for d in (book_dir / 'chapters').iterdir() if d.is_dir()}
    keys = {chapter_key(c['id']) for c in chapters}
    if dirs != keys:
        problems.append(f'G6 {tb}: 章目录 {sorted(dirs - keys)} 不在 seed；seed 章 {sorted(keys - dirs)} 无目录')

    fm_chapters: list[dict] = []
    for ch in chapters:
        key = chapter_key(ch['id'])
        ch_dir = book_dir / 'chapters' / key
        if not ch_dir.is_dir():
            continue
        start, end = ch['startPage'], ch['endPage']
        if end > printed_max:
            problems.append(f"G7 {ch['id']}: 章 endPage {end} 超出印刷页上限 {printed_max}（PDF 页号污染）")
        files = section_files(ch_dir)
        if not files:
            problems.append(f"G4 {ch['id']}: 章下没有节")
        nums = [section_no(f) for f in files]
        if nums != list(range(1, len(nums) + 1)):
            problems.append(f"G3 {ch['id']}: 节号须从 S1 起连续，实际 {nums}")
        sections: list[dict] = []
        for n, f in zip(nums, files):
            fm, body = read_doc(f)
            sid = f"{ch['id']}-S{n}"
            if fm.get('sectionId') != sid:
                problems.append(f"G3 {sid}: frontmatter sectionId={fm.get('sectionId')} 与文件名不符")
            pr = fm.get('pageRange')
            if not (isinstance(pr, list) and len(pr) == 2 and all(isinstance(x, int) for x in pr) and pr[0] <= pr[1]):
                problems.append(f'G2 {sid}: pageRange 须为 [a, b] 且 a ≤ b，实际 {pr}')
                continue
            if pr[0] < start or pr[1] > end:
                problems.append(f'G5 {sid}: pageRange {pr} 超出章 [{start}, {end}]')
            title = first_heading(body)
            if not title:
                problems.append(f'G2 {sid}: 正文没有标题行，无法取节 title')
                continue
            sections.append({'id': f'S{n}', 'title': title, 'order': n, 'pageRange': pr})
        ch_fm, _ = read_doc(ch_dir / 'index.md')
        fm_chapters.append({'id': key, 'title': ch_fm['title'], 'order': ch['order'],
                            'pageRange': [start, end], 'sections': sections})

    if problems:
        raise GateError(problems)
    return book_dir, {
        'textbookId': tb, 'title': book['title'], 'grade': book['grade'], 'term': book['term'],
        'subject': book['subject'], 'publisher': book['publisher'], 'totalPages': book['totalPages'],
        'imageOffset': book['pageOffset'], 'origin': 'textbook', 'outlineSource': 'section-files',
        'chapters': fm_chapters,
    }


def render_index(fm: dict) -> str:
    """与 book_apply.render_book_index 同构：front-matter 承载全部结构，body 只放一行标题。"""
    dumped = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{dumped}---\n\n# {fm['title']}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--seed', type=Path, required=True)
    ap.add_argument('--toc-root', type=Path, required=True)
    ap.add_argument('--only', action='append', default=[])
    ap.add_argument('--check', action='store_true', help='只跑门禁，不写盘')
    ap.add_argument('--force', action='store_true', help='覆盖已存在的书级 index.md')
    args = ap.parse_args(argv)

    books, chapters = load_seed(args.seed)
    ids = args.only or sorted(books)
    problems: list[str] = []
    rendered: list[tuple[Path, str]] = []
    for tb in ids:
        try:
            book_dir, fm = build_book(args.root / 'content', books[tb], chapters.get(tb, []), args.toc_root)
        except GateError as e:
            problems += e.problems
            continue
        if (book_dir / 'index.md').exists() and not args.force:
            problems.append(f'{tb}: 书级 index.md 已存在（knowledge 为单一事实源，重生成须 --force）')
            continue
        rendered.append((book_dir / 'index.md', render_index(fm)))
    for p in problems:
        print(f'✖ {p}', file=sys.stderr)
    if problems:
        print(f'{len(problems)} 个问题，未写任何文件', file=sys.stderr)
        return 1
    if not args.check:
        for path, text in rendered:
            path.write_text(text, encoding='utf-8')
    print(f"{'门禁通过' if args.check else '已写'} {len(rendered)} 本")
    return 0


if __name__ == '__main__':
    sys.exit(main())
