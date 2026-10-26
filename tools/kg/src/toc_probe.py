#!/usr/bin/env python3
"""TOC 探针：渲染 PDF 前 N 页并 OCR，输出文本以判断目录起止与正文起始。"""
from __future__ import annotations

import argparse
from pathlib import Path

import fitz
from rapidocr_onnxruntime import RapidOCR

REPO = Path(__file__).resolve().parents[4]


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
        text = item[1] if isinstance(item, (list, tuple)) else str(item)
        text = text.strip()
        if text:
            lines.append(text)
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', type=Path, required=True)
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--end', type=int, default=10)
    ap.add_argument('--scale', type=float, default=2.5)
    args = ap.parse_args()

    pdf = args.pdf if args.pdf.is_absolute() else REPO / args.pdf
    cache = args.cache if args.cache.is_absolute() else REPO / args.cache
    cache.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf))
    engine = RapidOCR()
    for pdf_1based in range(args.start, args.end + 1):
        pdf_idx = pdf_1based - 1
        if pdf_idx < 0 or pdf_idx >= doc.page_count:
            print(f'! skip pdf#{pdf_1based}: out of range')
            continue
        img = cache / f'p{pdf_1based:03d}.png'
        if not img.is_file():
            render_page(doc, pdf_idx, img, scale=args.scale)
        text = ocr_image(engine, img)
        (cache / f'p{pdf_1based:03d}.txt').write_text(text, encoding='utf-8')
        print(f'\n===== PDF page {pdf_1based} =====')
        print(text)
    doc.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
