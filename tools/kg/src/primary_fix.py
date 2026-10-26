#!/usr/bin/env python3
"""小学入图谱 P0.2 前置数据修复（spec：小学入图管线

子命令（默认 dry-run，--apply 才写盘）：
  single-range   单元素 pageRange [p] → [p, p]；仅在能证明是单页时补，其余列出待人工
  renumber       道法书节号改为每章从 S1 起（文件名与 sectionId 同改）
  check-pages    用 OCR 页文本核对节起始页（G5 差 1 页的章取证用）
  shift          整章节 pageRange 平移 N 页
  split-propose  无节章按页域切节：产出提议 JSON（未定页为 null，人工对照页图补）
  split-apply    按提议 JSON 写节文件

运行（在 knowledge/tools/kg 下）:
  python3 src/primary_fix.py single-range --root ../.. --seed seeds/primary-textbooks.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from primary_common import (
    chapter_blocks, chapter_key, find_page, first_heading, load_pages, load_seed, locate_book,
    read_doc, section_files, section_no, set_fm_line,
)


def fix_single_ranges(root: Path, seed: Path, apply: bool) -> tuple[list[str], list[str]]:
    books, chapters = load_seed(seed)
    fixed: list[str] = []
    manual: list[str] = []
    for tb in sorted(books):
        book_dir = locate_book(root / 'content', tb)
        for ch in chapters.get(tb, []):
            files = section_files(book_dir / 'chapters' / chapter_key(ch['id']))
            fms = [read_doc(f)[0] for f in files]
            for i, (f, fm) in enumerate(zip(files, fms)):
                pr = fm.get('pageRange')
                if not (isinstance(pr, list) and len(pr) == 1):
                    continue
                p = pr[0]
                if i + 1 < len(fms):
                    bound = (fms[i + 1].get('pageRange') or [None])[0]
                    provable = bound in (p, p + 1)
                else:
                    bound = ch['endPage']
                    provable = bound == p
                if not provable:
                    manual.append(f"{fm['sectionId']} [{p}]：下一节起始/章末 = {bound}，对照页图人工定")
                    continue
                fixed.append(fm['sectionId'])
                if apply:
                    f.write_text(set_fm_line(f.read_text(encoding='utf-8'), 'pageRange', f'[{p}, {p}]'),
                                 encoding='utf-8')
    return fixed, manual


def renumber_book(root: Path, textbook_id: str, apply: bool) -> list[tuple[str, str]]:
    """每章节号改为从 S1 起。只处理「连续但不从 1 起」的章；不连续即报错交人工。
    两阶段改名（先改临时名再落位），避免 S3→S2 撞上尚未搬走的 S2。"""
    book_dir = locate_book(root / 'content', textbook_id)
    moves: list[tuple[str, str]] = []
    ch_dirs = sorted((d for d in (book_dir / 'chapters').iterdir() if d.is_dir()), key=lambda d: int(d.name[1:]))
    for ch_dir in ch_dirs:
        files = section_files(ch_dir)
        nums = [section_no(f) for f in files]
        if not nums or nums[0] == 1:
            continue
        if nums != list(range(nums[0], nums[0] + len(nums))):
            raise ValueError(f'{ch_dir}: 节号不连续 {nums}，不自动重编号')
        plan = [(f, ch_dir / 'sections' / f'S{i}.md', f'{textbook_id}-{ch_dir.name}-S{i}')
                for i, f in enumerate(files, 1)]
        moves += [(f'{textbook_id}-{ch_dir.name}-S{section_no(src)}', sid) for src, _, sid in plan]
        if not apply:
            continue
        staged: list[tuple[Path, Path]] = []
        for src, dst, sid in plan:
            tmp = src.with_name(f'.renum-{dst.name}')
            tmp.write_text(set_fm_line(src.read_text(encoding='utf-8'), 'sectionId', sid), encoding='utf-8')
            src.unlink()
            staged.append((tmp, dst))
        for tmp, dst in staged:
            if dst.exists():
                raise FileExistsError(dst)
            tmp.rename(dst)
    return moves


def _chapter_index(seed: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    books, chapters = load_seed(seed)
    return books, {c['id']: c for lst in chapters.values() for c in lst}


def check_pages(root: Path, seed: Path, toc_root: Path, chapter_ids: list[str]) -> list[str]:
    """逐节：frontmatter 起始页 vs 标题在 OCR 页文本中的印刷页（在章范围外扩 2 页内找）。"""
    books, by_id = _chapter_index(seed)
    lines: list[str] = []
    for cid in chapter_ids:
        ch = by_id[cid]
        tb = ch['textbookId']
        lo, hi = max(1, ch['startPage'] - 2), ch['endPage'] + 2
        pages = load_pages(toc_root, tb, books[tb]['pageOffset'], lo, hi)
        lines.append(f"# {cid} PG=[{ch['startPage']}, {ch['endPage']}]")
        for f in section_files(locate_book(root / 'content', tb) / 'chapters' / chapter_key(cid)):
            fm, body = read_doc(f)
            got, _ = find_page([first_heading(body) or ''], pages, lo, hi)
            start = fm['pageRange'][0]
            lines.append(f"{fm['sectionId']}\tfm={start}\tocr={got}\tdelta={'?' if got is None else start - got}")
            if got is not None:
                lo = got
    return lines


def shift_chapter(root: Path, seed: Path, chapter_id: str, delta: int, apply: bool) -> list[str]:
    books, by_id = _chapter_index(seed)
    ch = by_id[chapter_id]
    out: list[str] = []
    for f in section_files(locate_book(root / 'content', ch['textbookId']) / 'chapters' / chapter_key(chapter_id)):
        fm, _ = read_doc(f)
        a, b = fm['pageRange']
        new = f'[{a + delta}, {b + delta}]'
        out.append(f"{fm['sectionId']} [{a}, {b}] → {new}")
        if apply:
            f.write_text(set_fm_line(f.read_text(encoding='utf-8'), 'pageRange', new), encoding='utf-8')
    return out


def propose_split(root: Path, seed: Path, toc_root: Path) -> list[dict]:
    books, chapters = load_seed(seed)
    out: list[dict] = []
    for tb in sorted(books):
        book_dir = locate_book(root / 'content', tb)
        for ch in chapters.get(tb, []):
            ch_dir = book_dir / 'chapters' / chapter_key(ch['id'])
            if section_files(ch_dir):
                continue
            _, body = read_doc(ch_dir / 'index.md')
            pages = load_pages(toc_root, tb, books[tb]['pageOffset'], ch['startPage'], ch['endPage'])
            lo = ch['startPage']
            items: list[dict] = []
            for i, b in enumerate(chapter_blocks(body)):
                page, src = find_page([b['heading'], b['anchor']], pages, lo, ch['endPage'])
                if page is None and i == 0:
                    page, src = ch['startPage'], 'chapter-start'
                items.append({'heading': b['heading'], 'page': page, 'source': src})
                if page is not None:
                    lo = page
            out.append({'chapterId': ch['id'], 'chapterDir': ch_dir.relative_to(root).as_posix(),
                        'startPage': ch['startPage'], 'endPage': ch['endPage'], 'blocks': items})
    return out


def apply_split(root: Path, proposal: list[dict], apply: bool) -> list[str]:
    out: list[str] = []
    for ch in proposal:
        cid, ch_dir = ch['chapterId'], root / ch['chapterDir']
        if section_files(ch_dir):
            raise FileExistsError(f'{ch_dir}/sections 已有节文件，拒绝覆盖')
        _, body = read_doc(ch_dir / 'index.md')
        blocks = chapter_blocks(body)
        if [b['heading'] for b in blocks] != [b['heading'] for b in ch['blocks']]:
            raise ValueError(f'{cid}: 提议与章正文的块不一致，重新 split-propose')
        pages = [b['page'] for b in ch['blocks']]
        if any(p is None for p in pages):
            raise ValueError(f'{cid}: 仍有块未定页：{[b["heading"] for b in ch["blocks"] if b["page"] is None]}')
        if pages != sorted(pages) or pages[0] < ch['startPage'] or pages[-1] > ch['endPage']:
            raise ValueError(f"{cid}: 块页码须单调不减且落在 [{ch['startPage']}, {ch['endPage']}]，实际 {pages}")
        groups: list[tuple[int, list[str]]] = []
        for b, p in zip(blocks, pages):
            if groups and groups[-1][0] == p:
                groups[-1][1].append(b['text'])
            else:
                groups.append((p, [b['text']]))
        for i, (start, texts) in enumerate(groups, 1):
            end = groups[i][0] - 1 if i < len(groups) else ch['endPage']
            text = '\n\n'.join(texts)
            out.append(f'{cid}-S{i} [{start}, {end}] {first_heading(text)}')
            if apply:
                (ch_dir / 'sections').mkdir(exist_ok=True)
                (ch_dir / 'sections' / f'S{i}.md').write_text(
                    f"---\nsectionId: {cid}-S{i}\npageRange: [{start}, {end}]\n"
                    f"derivedFrom: {ch['chapterDir']}/index.md\n---\n\n{text}\n", encoding='utf-8')
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('single-range')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--seed', type=Path, required=True)
    p.add_argument('--apply', action='store_true')

    p = sub.add_parser('renumber')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--book', action='append', required=True)
    p.add_argument('--apply', action='store_true')

    p = sub.add_parser('check-pages')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--seed', type=Path, required=True)
    p.add_argument('--toc-root', type=Path, required=True)
    p.add_argument('chapters', nargs='+')

    p = sub.add_parser('shift')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--seed', type=Path, required=True)
    p.add_argument('--chapter', required=True)
    p.add_argument('--delta', type=int, required=True)
    p.add_argument('--apply', action='store_true')

    p = sub.add_parser('split-propose')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--seed', type=Path, required=True)
    p.add_argument('--toc-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)

    p = sub.add_parser('split-apply')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--proposal', type=Path, required=True)
    p.add_argument('--apply', action='store_true')

    args = ap.parse_args(argv)
    if args.cmd == 'single-range':
        fixed, manual = fix_single_ranges(args.root, args.seed, args.apply)
        print(f"{'已补' if args.apply else '可补'} {len(fixed)} 节：" + ', '.join(fixed))
        for line in manual:
            print(f'待人工 {line}')
        return 1 if manual else 0
    if args.cmd == 'renumber':
        for tb in args.book:
            for old, new in renumber_book(args.root, tb, args.apply):
                print(f'{old} → {new}')
        return 0
    if args.cmd == 'check-pages':
        print('\n'.join(check_pages(args.root, args.seed, args.toc_root, args.chapters)))
        return 0
    if args.cmd == 'shift':
        print('\n'.join(shift_chapter(args.root, args.seed, args.chapter, args.delta, args.apply)))
        return 0
    if args.cmd == 'split-propose':
        prop = propose_split(args.root, args.seed, args.toc_root)
        args.out.write_text(json.dumps(prop, ensure_ascii=False, indent=1), encoding='utf-8')
        nulls = sum(b['page'] is None for c in prop for b in c['blocks'])
        print(f'{len(prop)} 章，{sum(len(c["blocks"]) for c in prop)} 块，未定页 {nulls} 块 → {args.out}')
        return 0
    if args.cmd == 'split-apply':
        prop = json.loads(args.proposal.read_text(encoding='utf-8'))
        print('\n'.join(apply_split(args.root, prop, args.apply)))
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
