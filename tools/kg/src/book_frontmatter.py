#!/usr/bin/env python3
"""书级 index.md front-matter 的唯一读取入口（分层 v3）。

2026-08-28 的 content 去 YAML 化把 43 个 `textbook.yaml` 折进了书级 `index.md` 的
front-matter，**全库现有 0 个 `textbook.yaml`**，但 OCR / 摄入 / 格式化这条管线上的
脚本没跟着迁，仍在 `open('textbook.yaml')`，整条摄入路径是断的（摄入路径断裂修复）。

本模块是那批脚本的共用读取入口——**只此一份解析，不要在各脚本里各写一遍**。

两条 fail-loud 纪律（CLAUDE.md §4.3）：
- front-matter 缺失/解析失败/无 `textbookId` 一律抛错，不返回空 dict；
- `imageOffset` 缺失时抛错而不是当 0 用。offset 猜错会让整章 OCR 系统性错页，
  而错得很像对的——imageOffset 缺失处置 记的那 21 本正是 `imageOffset: null`。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

FM_RE = re.compile(r'^---\n(.*?)\n---\n', re.S)


def parse_frontmatter(text: str, where: str) -> dict:
    """解析 md 头部的 YAML front-matter。无 front-matter 即抛错。"""
    m = FM_RE.match(text)
    if not m:
        raise ValueError(f'{where}: 文件开头没有 --- 包围的 front-matter')
    fm = yaml.safe_load(m.group(1))
    if not isinstance(fm, dict):
        raise ValueError(f'{where}: front-matter 不是映射，实际 {type(fm).__name__}')
    return fm


def read_book(tb_dir: Path) -> dict:
    """读取教材目录下的书级 index.md front-matter。"""
    p = tb_dir / 'index.md'
    if not p.is_file():
        raise FileNotFoundError(f'{p} 不存在（分层 v3 起书级元数据在 index.md，不再有 textbook.yaml）')
    fm = parse_frontmatter(p.read_text(encoding='utf-8'), str(p))
    if not fm.get('textbookId'):
        raise ValueError(f'{p}: front-matter 缺 textbookId')
    return fm


def find_book_dir(content_root: Path, textbook_id: str) -> Path:
    """在 content/<年级>/<学期>/<学科>/ 下按 textbookId 定位教材目录。"""
    for p in sorted(content_root.glob(f'*/*/*/{textbook_id}/index.md')):
        return p.parent
    raise FileNotFoundError(f'在 {content_root} 下找不到教材 {textbook_id}')


def chapters(book: dict) -> list[dict]:
    """章列表。只认 `chapters`——`units` 已于 2026-08-28 删除（双份结构裁决）。"""
    chs = book.get('chapters')
    if not isinstance(chs, list) or not chs:
        raise ValueError(f'{book.get("textbookId")}: front-matter 缺 chapters')
    return chs


def image_offset(book: dict) -> int:
    """书级 imageOffset。缺失即抛错，不退化成 0。"""
    off = book.get('imageOffset')
    if off is None:
        raise ValueError(
            f'{book.get("textbookId")}: imageOffset 缺失，无法把教材页号换算成页图编号'
            '（见 仓外治理记录（不入公开仓）imageOffset 缺失处置-missing-image-offset）。请先补齐该字段，不要按 0 处理'
        )
    return int(off)


def pdf_pages(book: dict, ch: dict) -> list[int]:
    """章的教材页码区间 → PDF 1-based 页码列表。

    2026-08-28 页码语义裁决（页码语义裁决（2026-08））：`pageRange` **恒为教材页号**，图像页号不落盘、
    由书级 `imageOffset` 现算。故此处只有一条路径，没有 imageRange 分支可选。
    """
    pr = ch.get('pageRange')
    if not (isinstance(pr, list) and len(pr) == 2):
        raise ValueError(f'{book.get("textbookId")} {ch.get("id")}: pageRange 缺失或格式不对')
    off = image_offset(book)
    return [p + off for p in range(int(pr[0]), int(pr[1]) + 1)]
