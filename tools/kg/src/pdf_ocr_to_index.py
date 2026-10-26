#!/usr/bin/env python3
"""
经济 OCR：PDF（扫描件）→ RapidOCR → chapters/Cn/index.md

优先本地 RapidOCR（无按页云费用）；内容校准由当前 agent 按 kg-repair S2 执行。

用法:
  python pdf_ocr_to_index.py \\
    --pdf path/to/book.pdf \\
    --textbook knowledge/content/七年级/下册/数学/BSDU-7-2-Math \\
    --chapter 1

  # 仅前 5 页试跑
  python pdf_ocr_to_index.py ... --chapter 1 --max-pages 5
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import fitz
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_frontmatter import image_offset, read_book  # noqa: E402

REPO = Path(__file__).resolve().parents[4]


def source_dir() -> Path:
    """教材源图目录。开源后经环境变量注入，缺失即退出。"""
    v = os.environ.get('KG_SOURCE_DIR')
    if not v:
        sys.exit('环境变量 KG_SOURCE_DIR 未设置：指向含 <教材id>/pages、metadata.json 的源图目录')
    return Path(v)


def load_textbook(tb_dir: Path) -> dict:
    """书级元数据。分层 v3 起在 index.md 的 front-matter 里（摄入路径断裂修复）。"""
    return read_book(tb_dir)


def _chapter_num(ch: dict):
    """统一取章号：兼容旧键 chapter/unit 与新键 id（如 C1/C2）。"""
    n = ch.get('chapter') or ch.get('unit') or ch.get('id')
    if n is None:
        return None
    s = str(n).strip()
    if s and s[0] in 'CUV' and s[1:].isdigit():
        return int(s[1:])
    try:
        return int(s)
    except ValueError:
        return None


def chapter_meta(tb: dict, chapter: int) -> dict:
    for ch in tb.get('chapters') or []:
        n = _chapter_num(ch)
        if n is not None and n == chapter:
            return ch
    raise KeyError(f'chapter {chapter} not in index.md front-matter')


def list_chapters(tb: dict) -> list[int]:
    out: list[int] = []
    for ch in tb.get('chapters') or []:
        n = _chapter_num(ch)
        if n is not None:
            out.append(n)
    return out


def resolve_pdf_pages(ch: dict, image_offset_value: int) -> list[int]:
    """章的教材页码区间 → PDF 1-based 页码列表。

    2026-08-28 页码语义裁决（页码语义裁决（2026-08））：`pageRange` **恒为教材页号**，图像页号不落盘、
    由书级 `imageOffset` 现算。裁决之前这里有两个临时物——`imageRange` 分支与
    `--allow-unverified-pagerange` 拒绝闸门——随裁决一并撤除，现在只剩一条路径。
    """
    pr = ch.get('pageRange')
    if not (isinstance(pr, list) and len(pr) == 2):
        raise ValueError(f'chapter {ch.get("id")}: pageRange 缺失或格式不对')
    a, b = int(pr[0]), int(pr[1])
    return [p + image_offset_value for p in range(a, b + 1)]


def textbook_page_to_pdf_index(tb_page: int, image_offset: int) -> int:
    """教材页码 → PDF 0-based index。imageOffset=5 表示教材 p1 对应 PDF 第 6 页。"""
    return tb_page + image_offset - 1

def render_page(doc: fitz.Document, pdf_index: int, out: Path, scale: float = 2.5) -> Path:
    page = doc[pdf_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    return out


def ocr_image(ocr_engine, img_path: Path) -> str:
    result, _ = ocr_engine(str(img_path))
    if not result:
        return ''
    lines = []
    for item in result:
        # item: [box, text, score]
        text = item[1] if isinstance(item, (list, tuple)) else str(item)
        text = text.strip()
        if text:
            lines.append(text)
    return '\n'.join(lines)


def join_cjk_spaces(text: str) -> str:
    """轻度清理：去掉中文间多余空格（Tesseract 风格残留）。"""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    return text


def heading_for(tb: dict, chapter_num: int, title: str) -> tuple[str, str]:
    """返回 (h1_line_with_newline, frontmatter_title)。"""
    subject = (tb.get('subject') or '').lower()
    if tb.get('units') and not tb.get('chapters'):
        if subject == 'english':
            return f'# Unit {chapter_num} {title}\n', f'Unit {chapter_num} {title}'
        return f'# 第{chapter_num}单元 {title}\n', f'第{chapter_num}单元 {title}'
    return f'# 第{chapter_num}章 {title}\n', f'第{chapter_num}章 {title}'


def build_index_md(
    *,
    chapter_num: int,
    chapter_id: str,
    title: str,
    pages: list[tuple[int, str]],
    h1: str,
    fm_title: str,
) -> str:
    body_parts = [h1]
    for label, text in pages:
        text = join_cjk_spaces(text).strip()
        if not text:
            continue
        body_parts.append(f'\n<!-- page {label} -->\n\n{text}\n')
    body = '\n'.join(body_parts).strip() + '\n'
    fm = f'---\nchapterId: {chapter_id}\ntitle: {fm_title}\n---\n\n'
    return fm + body


def resolve_pages_dir(textbook_id: str, pages_dir: Path | None) -> Path | None:
    if pages_dir and pages_dir.is_dir():
        return pages_dir
    images_dir = source_dir() / textbook_id / 'pages'
    return images_dir if images_dir.is_dir() else None


def ocr_one_chapter(
    *,
    pdf: Path,
    tb_dir: Path,
    tb: dict,
    chapter: int,
    engine_name: str,
    scale: float,
    max_pages: int | None,
    run_ocr,
    pages_dir: Path | None = None,
) -> Path:
    ch = chapter_meta(tb, chapter)
    title = ch.get('title') or f'第{chapter}章'
    # imageOffset 缺失即抛错，不按 0 处理——猜错会让整章系统性错页（imageOffset 缺失处置）
    offset = image_offset(tb)
    textbook_id = tb.get('textbookId') or tb_dir.name
    chapter_id = f'{textbook_id}-C{chapter}'
    pdf_pages = resolve_pdf_pages(ch, offset)
    if max_pages:
        pdf_pages = pdf_pages[:max_pages]

    # cache under knowledge/tools/kg/.ocr-cache
    knowledge_root = Path(__file__).resolve().parents[3]
    cache = knowledge_root / 'tools' / 'kg' / '.ocr-cache' / textbook_id / f'C{chapter}'
    cache.mkdir(parents=True, exist_ok=True)
    existing_pages = resolve_pages_dir(textbook_id, pages_dir)

    doc = fitz.open(str(pdf)) if pdf.is_file() else None
    pages_out: list[tuple[int, str]] = []
    print(
        f'OCR {textbook_id} C{chapter} 《{title}》 '
        f'pdf pages {pdf_pages[0]}-{pdf_pages[-1]} '
        f'(教材页 {ch["pageRange"][0]}-{ch["pageRange"][1]} + imageOffset {offset}'
        f'{", pages-dir" if existing_pages else ""})'
    )
    for pdf_1based in pdf_pages:
        pdf_idx = pdf_1based - 1
        txt_cache = cache / f'p{pdf_1based:03d}.txt'
        if txt_cache.is_file() and txt_cache.stat().st_size > 20:
            text = txt_cache.read_text(encoding='utf-8')
            print(f'  → pdf#{pdf_1based} (txt-cache)', flush=True)
            pages_out.append((pdf_1based, text))
            continue

        img = cache / f'p{pdf_1based:03d}.png'
        src_jpg = existing_pages / f'{pdf_1based}.jpg' if existing_pages else None
        if src_jpg and src_jpg.is_file():
            img = src_jpg
        elif not img.is_file():
            if doc is None or pdf_idx < 0 or pdf_idx >= doc.page_count:
                print(f'  ! skip pdf#{pdf_1based}: out of range')
                continue
            render_page(doc, pdf_idx, img, scale=scale)
        print(f'  → pdf#{pdf_1based}', flush=True)
        text = run_ocr(img)
        txt_cache.write_text(text, encoding='utf-8')
        pages_out.append((pdf_1based, text))
    if doc is not None:
        doc.close()

    out_dir = tb_dir / 'chapters' / f'C{chapter}'
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / 'index.md'
    h1, fm_title = heading_for(tb, chapter, title)
    index_path.write_text(
        build_index_md(
            chapter_num=chapter,
            chapter_id=chapter_id,
            title=title,
            pages=pages_out,
            h1=h1,
            fm_title=fm_title,
        ),
        encoding='utf-8',
    )
    print(f'写好: {index_path} ({index_path.stat().st_size} bytes, {len(pages_out)} pages)')
    return index_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', type=Path, required=True)
    ap.add_argument('--textbook', type=Path, required=True, help='教材目录（含书级 index.md）')
    ap.add_argument('--chapter', type=int, default=None)
    ap.add_argument('--all-chapters', action='store_true', help='处理 textbook 全部章/单元')
    ap.add_argument('--max-pages', type=int, default=None)
    ap.add_argument('--scale', type=float, default=2.5)
    ap.add_argument('--engine', choices=['rapid', 'tesseract'], default='rapid')
    ap.add_argument(
        '--pages-dir',
        type=Path,
        default=None,
        help='已导出的页图目录（KG_SOURCE_DIR/<id>/pages），优先于重新渲染 PDF',
    )
    args = ap.parse_args()

    pdf = args.pdf if args.pdf.is_absolute() else REPO / args.pdf
    tb_dir = args.textbook if args.textbook.is_absolute() else REPO / args.textbook
    if not pdf.is_file():
        print(f'警告: PDF 不存在: {pdf}（若提供 pages-dir 仍可继续）', file=sys.stderr)

    tb = load_textbook(tb_dir)
    if args.all_chapters:
        chapters = list_chapters(tb)
    elif args.chapter is not None:
        chapters = [args.chapter]
    else:
        print('请指定 --chapter N 或 --all-chapters', file=sys.stderr)
        return 1

    if args.engine == 'rapid':
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()

        def run_ocr(img: Path) -> str:
            return ocr_image(engine, img)
    else:
        import subprocess

        def run_ocr(img: Path) -> str:
            out_base = img.with_suffix('')
            subprocess.run(
                ['tesseract', str(img), str(out_base), '-l', 'chi_sim+eng', '--psm', '4'],
                check=True,
                capture_output=True,
            )
            return out_base.with_suffix('.txt').read_text(encoding='utf-8')

    pages_dir = args.pages_dir
    if pages_dir and not pages_dir.is_absolute():
        pages_dir = REPO / pages_dir

    for c in chapters:
        ocr_one_chapter(
            pdf=pdf,
            tb_dir=tb_dir,
            tb=tb,
            chapter=c,
            engine_name=args.engine,
            scale=args.scale,
            max_pages=args.max_pages,
            run_ocr=run_ocr,
            pages_dir=pages_dir,
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
