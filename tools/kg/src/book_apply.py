#!/usr/bin/env python3
"""内容注入管线第 ② 步：确认过的 outline.json → content/ 下的书骨架。

**纯确定性。** 不调 LLM、不做任何猜测；outline 里没写清楚的一律抛错。产出：

    content/<...>/<textbookId>/index.md                    书级 front-matter（原 textbook.yaml）
    content/<...>/<textbookId>/chapters/C<n>/index.md      章正文
    content/<...>/<textbookId>/chapters/C<n>/sections/S<m>.md   节正文

写入后**重新解析一遍产物并与 outline 逐字段比对**（沿用本仓 apply 脚本的 fail-loud 后置复核，
见 migrations/apply_items_to_md.py）：写对了不等于读得回来，只有回读一致才算落地。

用法:
  python book_apply.py --root ../.. --textbook-id EXT-Astronomy-Basics
  python book_apply.py --textbook-id EXT-... --dry-run    # 只打印将写哪些文件
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_frontmatter import parse_frontmatter  # noqa: E402
from book_outline import load_outline, outline_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# 书级 front-matter 的键序。固定顺序而非 dict 原序——同一本书重复 apply 应产出逐字节相同的文件。
BOOK_KEY_ORDER = (
    'title', 'grade', 'term', 'subject', 'publisher', 'standardEdition',
    'totalPages', 'imageOffset', 'origin', 'source',
)


def render_book_index(outline: dict) -> str:
    """书级 index.md：front-matter 承载全部结构，body 只放一行标题。"""
    meta = outline['meta']
    fm: dict = {'textbookId': outline['textbookId']}
    for k in BOOK_KEY_ORDER:
        if k in meta and meta[k] not in (None, ''):
            fm[k] = meta[k]
    fm['chapters'] = [_chapter_fm(ch) for ch in outline['chapters']]
    dumped = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f'---\n{dumped}---\n\n# {meta["title"]}\n'


def _chapter_fm(ch: dict) -> dict:
    """章的 front-matter 条目。pageRange 只在 outline 显式给出时才写——
    扩展知识没有纸质页码，绝不用行号冒充（页码语义裁决（2026-08） 已裁决 pageRange 恒为教材页号）。"""
    out: dict = {'id': ch['id'], 'title': ch['title'], 'order': ch['order']}
    if ch.get('pageRange'):
        out['pageRange'] = list(ch['pageRange'])
    sections = ch.get('sections') or []
    if sections:
        out['sections'] = [_section_fm(s) for s in sections]
    return out


def _section_fm(s: dict) -> dict:
    out: dict = {'id': s['id'], 'title': s['title'], 'order': s['order']}
    if s.get('pageRange'):
        out['pageRange'] = list(s['pageRange'])
    return out


def slice_lines(lines: list[str], lo: int, hi: int) -> str:
    """按 1-based 闭区间取正文，去掉首尾空行。"""
    seg = lines[lo - 1:hi]
    while seg and not seg[0].strip():
        seg.pop(0)
    while seg and not seg[-1].strip():
        seg.pop()
    return '\n'.join(seg)


def render_chapter(textbook_id: str, ch: dict, body: str) -> str:
    fm = f'---\nchapterId: {textbook_id}-{ch["id"]}\ntitle: {ch["title"]}\n---\n'
    return f'{fm}\n{body}\n'


def render_section(textbook_id: str, ch: dict, s: dict, body: str) -> str:
    lines = [f'sectionId: {textbook_id}-{ch["id"]}-{s["id"]}']
    if s.get('pageRange'):
        lines.append(f'pageRange: [{s["pageRange"][0]}, {s["pageRange"][1]}]')
    fm = '---\n' + '\n'.join(lines) + '\n---\n'
    return f'{fm}\n{body}\n'


def plan_writes(root: Path, outline: dict) -> list[tuple[Path, str]]:
    """产出 (路径, 内容) 清单。不落盘，供 dry-run 与实写共用同一条代码路径。"""
    tb_id = outline['textbookId']
    base = root / outline['contentDir']
    lines: list[str] = []
    for rel in outline['sourceMd']:
        p = root / rel
        if not p.is_file():
            raise SystemExit(f'素材 md 不存在: {p}')
        lines.extend(p.read_text(encoding='utf-8').split('\n'))

    writes: list[tuple[Path, str]] = [(base / 'index.md', render_book_index(outline))]
    for ch in outline['chapters']:
        ch_dir = base / 'chapters' / ch['id']
        writes.append((ch_dir / 'index.md', render_chapter(tb_id, ch, slice_lines(lines, ch['fromLine'], ch['toLine']))))
        for s in ch.get('sections') or []:
            writes.append((
                ch_dir / 'sections' / f'{s["id"]}.md',
                render_section(tb_id, ch, s, slice_lines(lines, s['fromLine'], s['toLine'])),
            ))
    return writes


def verify_written(root: Path, outline: dict) -> None:
    """后置复核：回读产物，断言书级 front-matter 的结构与 outline 一致。"""
    p = root / outline['contentDir'] / 'index.md'
    fm = parse_frontmatter(p.read_text(encoding='utf-8'), str(p))
    if fm.get('textbookId') != outline['textbookId']:
        raise SystemExit(f'后置复核失败 {p}: textbookId 回读为 {fm.get("textbookId")!r}')
    got = [(c.get('id'), len(c.get('sections') or [])) for c in (fm.get('chapters') or [])]
    want = [(c['id'], len(c.get('sections') or [])) for c in outline['chapters']]
    if got != want:
        raise SystemExit(f'后置复核失败 {p}: 章节结构回读为 {got}，期望 {want}')


def main() -> int:
    ap = argparse.ArgumentParser(description='outline.json → content/ 书骨架（确定性）')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--textbook-id', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='允许覆盖已存在的文件')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    outline = load_outline(outline_path(root, args.textbook_id))
    if not outline['chapters']:
        raise SystemExit(
            'outline.json 的 chapters 还是空的。先按 kg-ingest skill 填切分意见，'
            '确认后再 apply——本步不做任何猜测'
        )

    writes = plan_writes(root, outline)
    existing = [p for p, _ in writes if p.exists()]
    if existing and not args.force:
        raise SystemExit(
            f'以下 {len(existing)} 个文件已存在，拒绝静默覆盖（要覆盖请加 --force）:\n  '
            + '\n  '.join(str(p.relative_to(root)) for p in existing[:10])
        )

    for p, content in writes:
        print(('[dry-run] ' if args.dry_run else '') + str(p.relative_to(root)))
        if args.dry_run:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')

    if args.dry_run:
        print(f'\n[dry-run] 共 {len(writes)} 个文件，未写盘')
        return 0

    verify_written(root, outline)
    print(f'\n已写 {len(writes)} 个文件，后置复核通过')
    print('下一步：跑 kg:lint 确认结构合规，再走 extract（第 ③ 步）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
