#!/usr/bin/env python3
"""小学入图谱 P0 共用函数：seed 读取、教材目录定位、节文件读写、OCR 页锚点定位、章正文切块。

spec：小学入图管线 §3 P0.2
seed 归档 = tools/kg/seeds/primary-textbooks.json（摄入输入快照）；
OCR 页 = source_data/<ID>/ocr_pages/<图片序号>.txt，图片序号 = 印刷页 + pageOffset。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from book_frontmatter import FM_RE, parse_frontmatter

SEC_RE = re.compile(r'^S(\d+)\.md$')
PRIMARY_GRADES = {'1', '2', '3', '4', '5', '6'}


def load_seed(path: Path) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """→ (书 by id, 章列表 by textbookId，按 order 排)。"""
    data = json.loads(path.read_text(encoding='utf-8'))
    books = {t['id']: t for t in data['textbooks']}
    chapters: dict[str, list[dict]] = {}
    for c in data['chapters']:
        chapters.setdefault(c['textbookId'], []).append(c)
    for lst in chapters.values():
        lst.sort(key=lambda c: c['order'])
    return books, chapters


def locate_book(content_root: Path, textbook_id: str) -> Path:
    """content/<年级>/<册>/<学科>/<ID>。书级 index.md 可能尚不存在，故按 chapters/ 定位。"""
    hits = sorted(content_root.glob(f'*/*/*/{textbook_id}/chapters'))
    if len(hits) != 1:
        raise FileNotFoundError(f'{textbook_id}: 期望 1 个 chapters 目录，实际 {len(hits)}')
    return hits[0].parent


def chapter_key(chapter_id: str) -> str:
    """PEP-3-1-English-C7 → C7"""
    return chapter_id.rsplit('-', 1)[1]


def section_no(p: Path) -> int:
    m = SEC_RE.match(p.name)
    if not m:
        raise ValueError(f'{p}: 不是 S<n>.md')
    return int(m.group(1))


def section_files(ch_dir: Path) -> list[Path]:
    """节文件按节号数值排序（S10 在 S9 之后）。"""
    d = ch_dir / 'sections'
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if SEC_RE.match(p.name)), key=section_no)


def read_doc(p: Path) -> tuple[dict, str]:
    text = p.read_text(encoding='utf-8')
    m = FM_RE.match(text)
    if not m:
        raise ValueError(f'{p}: 文件开头没有 --- 包围的 front-matter')
    return parse_frontmatter(text, str(p)), text[m.end():]


def set_fm_line(text: str, key: str, value: str) -> str:
    """只改 front-matter 中 `key:` 那一行，其余字节不动（保留 `[a, b]` 流式写法）。"""
    m = FM_RE.match(text)
    if not m:
        raise ValueError('文件开头没有 front-matter')
    head, n = re.subn(rf'^{re.escape(key)}:.*$', f'{key}: {value}', m.group(1), count=1, flags=re.M)
    if n != 1:
        raise ValueError(f'front-matter 缺 {key}')
    return f'---\n{head}\n---\n' + text[m.end():]


def first_heading(body: str) -> str | None:
    for line in body.split('\n'):
        if line.startswith('#'):
            return line.lstrip('#').strip()
    return None


def norm(s: str) -> str:
    """OCR 比对口径：小写，只留数字、拉丁字母、汉字。"""
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]', '', s.lower())


def load_pages(toc_root: Path, textbook_id: str, offset: int, lo: int, hi: int) -> dict[int, str]:
    """印刷页 → 规范化 OCR 文本；缺页为空串（找不到即交人工，不猜）。"""
    out: dict[int, str] = {}
    for page in range(lo, hi + 1):
        p = toc_root / textbook_id / 'ocr_pages' / f'{page + offset}.txt'
        out[page] = norm(p.read_text(encoding='utf-8')) if p.is_file() else ''
    return out


def find_page(anchors: list[str], pages: dict[int, str], lo: int, hi: int) -> tuple[int | None, str | None]:
    """按锚点优先级（标题 > 首行正文）在 [lo, hi] 找首个命中页。
    锚点规范化后取前 24 字，不足 4 字的不用（太短必误命中）。"""
    sources = ('heading', 'anchor')
    for i, a in enumerate(anchors):
        key = norm(a)[:24]
        if len(key) < 4:
            continue
        for page in range(lo, hi + 1):
            if key in pages.get(page, ''):
                return page, sources[min(i, 1)]
    return None, None


def first_content_line(lines: list[str]) -> str:
    """块内首个可作锚点的正文行：跳过空行、标题、插图占位、表格。"""
    for line in lines:
        s = line.strip()
        if s and not s.startswith(('#', '【图', '|')):
            return s
    return ''


def chapter_blocks(body: str) -> list[dict]:
    """章正文 → `## ` 块列表。首个 `## ` 之前的内容（`# ` 章标题行除外）并入第一块；
    无 `## ` 的章整章一块，保留 `# ` 行作节标题。"""
    lines = body.strip('\n').split('\n')
    if not any(line.startswith('## ') for line in lines):
        return [{'heading': first_heading(body) or '', 'text': '\n'.join(lines), 'anchor': first_content_line(lines)}]
    blocks: list[dict] = []
    pre: list[str] = []
    for line in lines:
        if line.startswith('## '):
            blocks.append({'heading': line[3:].strip(), 'lines': [line]})
        elif blocks:
            blocks[-1]['lines'].append(line)
        elif not line.startswith('# '):
            pre.append(line)
    while pre and not pre[-1].strip():
        pre.pop()
    if any(line.strip() for line in pre):
        blocks[0]['lines'] = pre + [''] + blocks[0]['lines']
    return [{'heading': b['heading'], 'text': '\n'.join(b['lines']).strip('\n'),
             'anchor': first_content_line(b['lines'])} for b in blocks]
