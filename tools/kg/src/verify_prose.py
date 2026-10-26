#!/usr/bin/env python3
"""
内容准确性校准（第一层·确定性）：原始 PDF 逐页重 OCR，与 sections/S*.md 正文 diff。

背景（2026-09-27 空壳事故修复后）：回填正文来自 git 历史（RapidOCR+三道 LLM 精修），
需对照原始 PDF 验证忠实度。本层只做确定性比对，差异裁决（LLM/人工）为第二层。

数据流:
  KG_SOURCE_DIR/<id>/*.pdf --fitz 渲染(scale2.5)--> RapidOCR --> 识别文本
  content/**/sections/S*.md 正文(去 frontmatter/标题/表格/插图区/图占位) <--- 归一化 diff --->

产出:
  tools/kg/state/verify/<tbId>.json   每节 similarity/diffs/formula_risk
  tools/kg/state/verify/summary.md    汇总
OCR 结果按 PDF 页缓存（state/verify/cache/<tbId>/p<N>.txt），中断可续。

用法:
  python3 verify_prose.py PEP-7-1-History --chapters C1,C3
  python3 verify_prose.py --all --per-book 2      # 每本书 2 章（C1 + 中间章）
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).parent))
from book_frontmatter import read_book, image_offset  # noqa: E402

import fitz  # noqa: E402
from rapidocr_onnxruntime import RapidOCR  # noqa: E402

OUT = REPO / 'knowledge' / 'tools' / 'kg' / 'state' / 'verify'
CACHE = OUT / 'cache'
GRADE = {'1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'}
TERM = {'1': '上册', '2': '下册', '0': '全一册'}


def load_env() -> None:
    env = REPO / 'knowledge' / '.env'
    if not env.is_file():
        return
    for line in env.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^([A-Z_]+)=(.*)$', line.strip())
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip()


def source_dir() -> Path:
    v = os.environ.get('KG_SOURCE_DIR')
    if not v:
        sys.exit('KG_SOURCE_DIR 未设置（knowledge/.env）')
    return Path(v)


def find_pdf(src: Path, tb: dict) -> Path:
    """定位教材 PDF：优先扁平化命名 pdf_sources/<BookId>.pdf；退回 subject+年级+册 关键词匹配。"""
    exact = src / f"{tb.get('textbookId')}.pdf"
    if exact.is_file():
        return exact
    subject = tb.get('subject', '')
    key = f"{GRADE.get(str(tb.get('grade')), str(tb.get('grade')))}年级{TERM.get(str(tb.get('term')), '')}"
    cands = [p for p in src.glob('*.pdf')
             if subject in p.name and key in re.sub(r'\s', '', p.stem)]
    if len(cands) == 1:
        return cands[0]
    if not cands:  # 兜底：全部 PDF 里按 subject 模糊
        cands = [p for p in src.glob('*.pdf') if subject in p.name]
    if len(cands) == 1:
        return cands[0]
    raise FileNotFoundError(f'{tb.get("textbookId")}: PDF 匹配到 {len(cands)} 个: {cands[:3]}')


def norm_text(s: str) -> str:
    """宽松归一化：NFKC、去空白/常见中英标点/markdown 标记/LaTeX 标记——衡量内容字符级一致性。"""
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\s，。、；：？！“”‘’（）【】《》…—·\-–—,.!?;:"\'()\[\]{}<>~%‰|*_#`$\\\\]+', '', s)
    return s


BLOCK_WHITELIST = {'插图', '解题模型', '笔记', '总结', '生字', '单词', '短语', '句子'}


def section_prose(text: str) -> str:
    """正文提取（与巡检口径一致）：跳过全部 v4 白名单区块（它们是附加内容非教材正文）。"""
    text = re.sub(r'^---.*?\n---\n', '', text, flags=re.S)
    lines, in_block = [], False
    for line in text.split('\n'):
        if line.startswith('## '):
            in_block = line.strip()[3:].strip() in BLOCK_WHITELIST
            continue
        if line.startswith('#') or line.startswith('|') or in_block:
            continue
        if re.match(r'^【图：.+】$', line.strip()):
            continue
        lines.append(line)
    return '\n'.join(lines)


def ocr_pdf_pages(pdf: Path, tb_pages: list[int], offset: int, ocr, tb_id: str) -> str:
    """教材页码列表 → OCR 文本（按 PDF 物理页缓存）。"""
    doc = fitz.open(str(pdf))
    out = []
    for tp in tb_pages:
        idx = tp + offset - 1
        if idx < 0 or idx >= doc.page_count:
            continue
        cache = CACHE / tb_id / f'p{idx + 1}.txt'
        if cache.is_file():
            out.append(cache.read_text(encoding='utf-8'))
            continue
        img = CACHE / tb_id / f'p{idx + 1}.jpg'
        page = doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
        img.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(img))
        text = ocr_image(ocr, img)
        cache.write_text(text, encoding='utf-8')
        img.unlink(missing_ok=True)  # 图不占盘，只留文本缓存
        out.append(text)
    doc.close()
    return join_cjk_spaces('\n'.join(out))


def join_cjk_spaces(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    return text


def ocr_image(ocr, img_path: Path) -> str:
    result, _ = ocr(str(img_path))
    if not result:
        return ''
    lines = []
    for item in result:
        t = item[1] if isinstance(item, (list, tuple)) else str(item)
        if t and t.strip():
            lines.append(t.strip())
    return '\n'.join(lines)


def shingle_misses(a: str, b: str, n: int = 10, limit: int = 20) -> tuple[float, list[str]]:
    """主指标：a 的 n 字滑窗在 b 中的命中率（内容存在性，对版式行序鲁棒）。
    返回 (覆盖率, 未命中片段)。"""
    total = max(1, len(a) - n + 1)
    hits = 0
    misses = []
    for i in range(0, len(a) - n + 1):
        seg = a[i:i + n]
        if seg in b:
            hits += 1
        elif len(misses) < limit * 3:  # 收集时去重合并相邻
            misses.append(seg)
    # 合并相邻 miss 片段
    merged: list[str] = []
    for seg in misses:
        if merged and a.find(seg) == a.find(merged[-1]) + len(merged[-1]):
            merged[-1] += seg[-1]
        else:
            merged.append(seg)
    return round(hits / total, 4), merged[:limit]


def diff_blocks(a: str, b: str, limit: int = 15) -> list[dict]:
    """正文侧未匹配片段（a 中在 OCR 里找不到的内容），带上下文。"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    blocks = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal' or op == 'insert':  # insert=b 侧多出（页眉/旁注，正常）
            continue
        ctx_a = a[max(0, i1 - 10):i1] + '▚' + a[i1:i2][:60] + '▚' + a[i2:i2 + 10]
        ocr_hit = b[max(0, j1 - 10):j1] + '▚' + b[j1:j2][:60] + '▚' + b[j2:j2 + 10]
        blocks.append({'op': op, 'prose': ctx_a, 'ocr': ocr_hit})
        if len(blocks) >= limit:
            break
    return blocks


def verify_section(sec_md: Path, sec_meta: dict, pdf: Path, offset: int, ocr, tb_id: str) -> dict:
    raw = sec_md.read_text(encoding='utf-8')
    prose = section_prose(raw)
    pr = sec_meta.get('pageRange')
    if not (isinstance(pr, list) and len(pr) == 2):
        return {'section': sec_md.stem, 'status': 'no-pageRange'}
    tb_pages = list(range(int(pr[0]), int(pr[1]) + 1))
    ocr_text = ocr_pdf_pages(pdf, tb_pages, offset, ocr, tb_id)
    a, b = norm_text(prose), norm_text(ocr_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # 覆盖率 = 正文内容在整页 OCR 中的匹配比例（OCR 含页眉/旁注/练习框，ratio 不适用）
    matched = sum(bl.size for bl in sm.get_matching_blocks())
    coverage = round(matched / len(a), 4) if a else 0.0
    # 主指标：10 字滑窗命中率——内容存在性，对多栏排版行序鲁棒
    shingle, miss_segs = shingle_misses(a, b)
    # 无序覆盖率：Counter 交集 / 正文长——不受版式行序影响。
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    bag = round(sum(min(c, cb.get(ch, 0)) for ch, c in ca.items()) / len(a), 4) if a else 0.0
    formula_risk = bool(re.search(r'\$|\\frac|\\times|\\div', prose)) or \
        sum(1 for l in prose.split('\n') if l.startswith('|')) >= 2
    res = {
        'section': sec_md.stem,
        'title': sec_meta.get('title', ''),
        'pages': f'{pr[0]}-{pr[1]}',
        'prose_chars': len(a),
        'ocr_chars': len(b),
        'shingle': shingle,
        'coverage': coverage,
        'bag_coverage': bag,
        'formula_risk': formula_risk,
        'misses': miss_segs if shingle < 0.95 else [],
    }
    return res


def pick_sections(tb: dict, per_book: int, chapters: list[str] | None, all_ch: bool = False) -> list[tuple[dict, dict]]:
    """[(chapter, section)] 选节：--chapters 指定章；--all-chapters 全章；否则 C1 + 中间章。"""
    chs = tb.get('chapters') or []
    if chapters:
        sel = [c for c in chs if c.get('id') in chapters]
    elif all_ch:
        sel = list(chs)
    elif chs:
        # 默认（per_book>=2）：C1 + 中间章；per_book=1 仅 C1（修复 per_book 分支缺失致 sel 未定义）
        idx = [0] if (per_book or 0) < 2 or len(chs) < 2 else [0, len(chs) // 2]
        sel = [c for i, c in enumerate(chs) if i in idx]
    else:
        sel = []
    out = []
    for c in sel:
        for s in c.get('sections') or []:
            out.append((c, s))
    return out


def verify_book(tb_id: str, src: Path, ocr, per_book: int, chapters: list[str] | None,
                all_ch: bool = False) -> dict:
    book_dirs = list((REPO / 'knowledge' / 'content').glob(f'*/*/*/{tb_id}'))
    if len(book_dirs) != 1:
        raise FileNotFoundError(f'{tb_id}: content 书目录找到 {len(book_dirs)} 个')
    book_dir = book_dirs[0]
    tb = read_book(book_dir)
    tb['textbookId'] = tb_id
    pdf = find_pdf(src, tb)
    offset = image_offset(tb)
    sec_dir = book_dir / 'chapters'

    report = {'textbookId': tb_id, 'pdf': pdf.name, 'imageOffset': offset, 'sections': []}
    for ch, sec in pick_sections(tb, per_book, chapters, all_ch):
        md = sec_dir / ch['id'] / 'sections' / f"{sec['id']}.md"
        if not md.is_file():
            report['sections'].append({'section': sec['id'], 'status': 'no-md'})
            continue
        r = verify_section(md, sec, pdf, offset, ocr, tb_id)
        r['chapter'] = ch['id']
        report['sections'].append(r)
        print(f"  [{r.get('shingle', 0):.3f}] {ch['id']}/{sec['id']} "
              f"{r.get('title', '')[:20]} (p{r.get('pages', '?')}, "
              f"{'公式风险' if r.get('formula_risk') else '普通'})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{tb_id}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                       encoding='utf-8')
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('book', nargs='?', help='textbookId；与 --all 二选一')
    ap.add_argument('--all', action='store_true', help='全部 43 本')
    ap.add_argument('--per-book', type=int, default=2, help='每本书选几章（默认 2：C1+中间章）')
    ap.add_argument('--all-chapters', action='store_true', help='全书所有章')
    ap.add_argument('--chapters', help='逗号分隔章节 id（仅单书模式）')
    args = ap.parse_args()
    load_env()
    src = source_dir()
    ocr = RapidOCR()

    if args.all:
        books = sorted(p.name for p in src.iterdir()
                       if p.is_dir() and (p / 'metadata.json').is_file())
    elif args.book:
        books = [args.book]
    else:
        ap.error('需要 book 或 --all')

    all_reports = []
    for tb_id in books:
        print(f'== {tb_id}')
        try:
            all_reports.append(verify_book(tb_id, src, ocr, args.per_book,
                                           args.chapters.split(',') if args.chapters else None,
                                           all_ch=args.all_chapters))
        except Exception as e:  # 单书失败不阻断批量
            print(f'  ERROR: {e}')
            all_reports.append({'textbookId': tb_id, 'error': str(e)})

    # 汇总
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ['# 内容准确性校验汇总（原始 PDF 重 OCR vs 正文，10 字滑窗命中率）', '',
             '判定：≥0.92 通过；0.85-0.92 关注；<0.85 可疑（内容真缺失/越界）', '',
             '| 教材 | 节数 | 平均 shingle | <0.92 | <0.85 | 公式风险 |', '|---|---|---|---|---|---|']
    for r in all_reports:
        if 'error' in r:
            lines.append(f"| {r['textbookId']} | ERROR: {r['error'][:40]} | - | - | - | - |")
            continue
        secs = [s for s in r['sections'] if 'shingle' in s]
        avg = sum(s['shingle'] for s in secs) / len(secs) if secs else 0
        low = sum(1 for s in secs if s['shingle'] < 0.92)
        very_low = sum(1 for s in secs if s['shingle'] < 0.85)
        fr = sum(1 for s in secs if s['formula_risk'])
        lines.append(f"| {r['textbookId']} | {len(secs)} | {avg:.3f} | {low} | {very_low} | {fr} |")
    summary = '\n'.join(lines)
    (OUT / 'summary.md').write_text(summary, encoding='utf-8')
    print('\n' + summary)
    print(f'\nreports -> {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
