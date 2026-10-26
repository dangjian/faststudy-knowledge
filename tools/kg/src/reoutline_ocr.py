#!/usr/bin/env python3
"""按台账 OCR 补齐节级正文（设计 §4 apply 步骤 a 的独立化：OCR+LLM 非确定性，单独成命令，apply 保持纯确定性）。

引擎：本地 RapidOCR（用户裁决：不用阿里云）。LLM 链复用既有脚本 polish→repair→format_refine。

用法（在 knowledge 仓根）:
  pnpm kg:reoutline:ocr --textbook BSDU-8-2-Math
  pnpm kg:reoutline:ocr --textbook BSDU-8-2-Math --sections C1-S2 C2-S1   # 只跑指定节
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = Path(__file__).resolve().parent

sys.path.insert(0, str(SRC))
from reoutline_propose import norm_title  # 与 PG↔图谱标题一致判定共用同一归一函数（三档序数剥离）


def source_dir() -> Path:
    """教材源图目录。开源后经环境变量注入，缺失即退出。"""
    v = os.environ.get('KG_SOURCE_DIR')
    if not v:
        sys.exit('环境变量 KG_SOURCE_DIR 未设置：指向含 <教材id>/pages、metadata.json 的源图目录')
    return Path(v)


def resolve_offset(ch: dict) -> int:
    """章级 imageOffset。缺失即 SystemExit（imageOffset 缺失处置 裁决：不当 0 用）。

    显式 0 合法（前置页为 0 的书真实存在）。
    """
    off = ch.get('imageOffset')
    if off is None:
        raise SystemExit(
            f'{ch.get("chapterId") or ch.get("dir") or "未知章"}: '
            'imageOffset 未标定（imageOffset 缺失处置），无法把教材页号换算成页图编号。'
            '请打开页图对照印刷页码与书页差值标定（如教材 p1 在页图第 6 张则 offset=5），不要按 0 处理。'
        )
    return int(off)


# 页脚水印清洗（2026-09-18：人民教育出版社美术字被 OCR 误读出 30+ 变体混入正文，
# LLM 精修链不删页脚样板，故在 OCR 原文层确定性剥离。详见 polish_format.py 规则 0（2026-10-15 并入））
_FOOTER_RE = re.compile(
    r'^\s*(?:Page\s+\d{1,3}\s*)?'
    r'人民[\s為敎0-9]{0,2}[育龍龙府加杂敎教]{0,2}[\s]?出[\s版颇殿直尔]{0,2}社'
    r'\s*(?:\d{1,3})?\s*$'
)
_FOOTER_INLINE = re.compile(
    r'人民[\s為敎0-9]{0,2}[育龍龙府加杂敎教]{0,2}[\s]?出[\s版颇殿直尔]{0,2}社'
)


def strip_footer(text: str) -> str:
    lines = []
    for ln in text.split('\n'):
        if _FOOTER_RE.match(ln):
            continue
        m = re.match(r'^(' + _FOOTER_INLINE.pattern + r')(?=\S)', ln)
        if m and len(ln) - len(m.group(0)) > 10:
            ln = ln[len(m.group(0)):]
        else:
            m2 = re.search(r'(?<=\S)(' + _FOOTER_INLINE.pattern + r')\s*$', ln)
            if m2 and len(ln) - len(m2.group(1)) > 10:
                ln = ln[:m2.start()]
        lines.append(ln)
    return '\n'.join(lines)


def ocr_page(ocr, img: Path) -> str:
    result, _ = ocr(str(img))
    return strip_footer('\n'.join(str(line[1]) for line in (result or [])))


def llm_chain(prose_file: Path) -> None:
    """外部 API 校准链已移除（2026-10-15 用户裁决）：内容校准由当前 agent 按 kg-repair S2
    在上下文中直接执行（忠实转写/不改题意/uncertain 旁路），本函数仅提示移交。"""
    print(f'  📄 prose 原文就绪：{prose_file.name} —— 内容校准由当前 agent 按 kg-repair S2 执行')


def main() -> int:
    ap = argparse.ArgumentParser(description='节级 OCR 补齐（RapidOCR 本地 + LLM 链）')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--textbook', required=True)
    ap.add_argument('--sections', nargs='*', help='只跑指定节（如 C1-S2），缺省跑全部 ocr 节')
    ap.add_argument('--force', action='store_true', help='已存在的 prose 文件也重跑')
    ap.add_argument('--dry-run', action='store_true', help='只列页图范围，不 OCR 不调 LLM')
    args = ap.parse_args()
    root = Path(args.root)

    ledger = json.loads((root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'reoutline.json').read_text(encoding='utf-8'))
    images_dir = source_dir() / args.textbook / 'pages'
    if not images_dir.is_dir():
        raise SystemExit(f'页图目录不存在：{images_dir}')
    prose_dir = root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'prose'
    prose_dir.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()

    report = {}
    for ch in ledger['chapters']:
        offset = resolve_offset(ch)
        for s in ch['sections']:
            key = f"{ch['dir'].split('/')[-1]}-{s['sId']}"
            if s['proseSource'] != 'ocr':
                continue
            if args.sections and key not in args.sections:
                continue
            prose_file = prose_dir / f'{key}.md'
            if prose_file.exists() and not args.force:
                report[key] = 'skipped-existing'
                continue
            lo, hi = s['pageRange']
            pages = list(range(lo + offset, hi + offset + 1))
            missing = [p for p in pages if not (images_dir / f'{p}.jpg').is_file()]
            if missing:
                raise SystemExit(f'{key}: 页图缺失 {missing[:5]}...（检查 imageOffset 换算，图片号=页号+{offset}）')
            print(f'📖 {key}: pages {lo}-{hi} (图片 {pages[0]}-{pages[-1]})')
            if args.dry_run:
                report[key] = f'dry-run pages {pages[0]}-{pages[-1]}'
                continue
            parts = []
            for i, p in enumerate(pages):
                text = ocr_page(ocr, images_dir / f'{p}.jpg')
                if i == 0:
                    core_title = norm_title(s['title'])
                    if core_title and core_title not in text:
                        print(f'[reoutline] WARN {key}: 首页未探到节标题「{s["title"]}」（检查 imageOffset 标定）')
                parts.append(f'<!-- page {p} -->\n{text}')
            prose_file.write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
            llm_chain(prose_file)
            report[key] = 'done'

    report_path = root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'ocr-report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'\n✅ {report_path}：{sum(1 for v in report.values() if v == "done")} done / {len(report)} 节')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
