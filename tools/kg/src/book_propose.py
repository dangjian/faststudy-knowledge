#!/usr/bin/env python3
"""内容注入管线第 ① 步：扫 md 的标题层级，产出 outline.json 骨架。

**确定性，不调 LLM，不写 content/。** 它只把「这份 md 有哪些标题、各占多少字」摆出来，
章节怎么切由 agent 在下一步填进 outline.json 的 `chapters`，人过目后再跑 book_apply.py。

之所以不在这里直接调 LLM 一把跑完：切分结果不留痕就无法复核，改一次章节要整本重跑，
出错也分不清是 LLM 判错还是脚本写错。见 spec「决策 1」。

用法:
  python book_propose.py --root ../.. --textbook-id EXT-Astronomy-Basics \\
      --md notes/astronomy.md --subject Astronomy --grade 7 --term 1 \\
      --title 天文学基础 --source '《XXX》第 3 版'

  # 多份 md（按给定顺序拼接，每份之间不插入任何内容）
  python book_propose.py ... --md a.md --md b.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_outline import dump_outline, outline_path, validate_outline  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
HEADING_RE = re.compile(r'^(#{1,4})\s+(.*\S)\s*$')
FENCE_RE = re.compile(r'^\s*(```|~~~)')


def scan_headings(lines: list[str]) -> list[dict]:
    """扫标题。围栏代码块内的 # 不算标题——否则含代码的素材会被切得稀碎。"""
    found: list[dict] = []
    in_fence = False
    for no, line in enumerate(lines, start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            found.append({'level': len(m.group(1)), 'line': no, 'text': m.group(2)})
    # 每个标题到下一个标题之间的字数，供切分时判断轻重
    for i, h in enumerate(found):
        end = found[i + 1]['line'] - 1 if i + 1 < len(found) else len(lines)
        h['chars'] = sum(len(line.strip()) for line in lines[h['line']:end])
    return found


def read_md(root: Path, rels: list[str]) -> list[str]:
    lines: list[str] = []
    for rel in rels:
        p = (root / rel) if not Path(rel).is_absolute() else Path(rel)
        if not p.is_file():
            raise FileNotFoundError(f'素材 md 不存在: {p}')
        lines.extend(p.read_text(encoding='utf-8').split('\n'))
    return lines


def build_outline(args: argparse.Namespace, headings: list[dict]) -> dict:
    meta = {
        'title': args.title,
        'grade': args.grade,
        'term': args.term,
        'subject': args.subject,
        'publisher': args.publisher,
        'origin': args.origin,
        'totalPages': args.total_pages,
    }
    if args.source:
        meta['source'] = args.source
    if args.standard_edition:
        meta['standardEdition'] = args.standard_edition
    if args.image_offset is not None:
        meta['imageOffset'] = args.image_offset
    return {
        'textbookId': args.textbook_id,
        'contentDir': args.content_dir or default_content_dir(args),
        'meta': meta,
        'sourceMd': args.md,
        'headings': headings,
        'chapters': [],
    }


GRADE_ZH = {'7': '七年级', '8': '八年级', '9': '九年级'}
TERM_ZH = {'1': '上册', '2': '下册', '0': '全一册'}


def default_content_dir(args: argparse.Namespace) -> str:
    """默认落盘目录。学科目录名默认取 --subject-dir，缺省时退回 --subject——
    既有库里学科目录名与 subject 字段并不一一对应，故此值可在 outline 里人工改。"""
    grade = GRADE_ZH.get(args.grade)
    term = TERM_ZH.get(args.term)
    if grade is None or term is None:
        raise SystemExit(
            f'grade/term 取值超出既有目录约定（grade ∈ {sorted(GRADE_ZH)}，term ∈ {sorted(TERM_ZH)}），'
            f'实际 {args.grade!r}/{args.term!r}。要放到别处请显式传 --content-dir'
        )
    subject_dir = args.subject_dir or args.subject
    return f'content/{grade}/{term}/{subject_dir}/{args.textbook_id}'


def main() -> int:
    ap = argparse.ArgumentParser(description='md → outline.json 骨架（确定性，不调 LLM）')
    ap.add_argument('--root', default=str(ROOT), help='knowledge 仓库根')
    ap.add_argument('--textbook-id', required=True)
    ap.add_argument('--md', action='append', required=True, help='素材 md（相对仓库根），可重复')
    ap.add_argument('--title', required=True)
    ap.add_argument('--grade', required=True)
    ap.add_argument('--term', required=True)
    ap.add_argument('--subject', required=True, help='写进 front-matter 的 subject 字段')
    ap.add_argument('--subject-dir', default='', help='content/ 下的学科目录名，缺省同 --subject')
    ap.add_argument('--content-dir', default='', help='直接指定落盘目录，覆盖 grade/term/subject 推导')
    ap.add_argument('--origin', choices=['textbook', 'extension'], default='extension')
    ap.add_argument('--publisher', default='-', help='扩展知识无出版社，默认 "-"')
    ap.add_argument('--source', default='', help='扩展知识必填：来源出处')
    ap.add_argument('--total-pages', type=int, default=0)
    ap.add_argument('--standard-edition', default='', choices=['', '2011版', '2022版'])
    ap.add_argument('--image-offset', type=int, default=None)
    ap.add_argument('--force', action='store_true', help='覆盖已存在的 outline.json')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = outline_path(root, args.textbook_id)
    if out.exists() and not args.force:
        # 不静默覆盖：outline 里可能已有人工确认过的切分
        raise SystemExit(f'{out} 已存在。要重新生成请显式加 --force（会丢掉已填的 chapters）')

    headings = scan_headings(read_md(root, args.md))
    if not headings:
        raise SystemExit(
            f'素材里一个 md 标题都没有：{args.md}。'
            '章节切分依赖标题层级，请先在素材里标出 # / ## 结构'
        )

    outline = build_outline(args, headings)
    validate_outline(outline, str(out))
    dump_outline(out, outline)

    print(f'已写 {out}')
    print(f'共 {len(headings)} 个标题：')
    for h in headings:
        print(f'  L{h["level"]}  行 {h["line"]:>5}  {h["chars"]:>6} 字  {h["text"]}')
    print('\n下一步：按 kg-ingest skill 把切分意见填进 outline.json 的 chapters，再跑 book_apply.py')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
