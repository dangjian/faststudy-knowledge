#!/usr/bin/env python3
"""核对教材 PDF 与数据里的页码是否对得上（只读）。

语义（已用 PEP-1-1-Chinese 实测确认）：
  pageRange   = **印刷页码**
  PDF/图片页  = 印刷页码 + textbook.imageOffset
              （PDF 第 7 页正文里印着「2」，该册 imageOffset=5，7 = 2 + 5）

三件事：
1. **越界**：印刷页码 + imageOffset 超过 PDF 实际页数 → 读者/agent 翻不到。
2. **对位**：拿节的正文开头去 PDF 对应页找，找不到说明页码或偏移错。
3. **文本层**：统计无文本层的页数（扫描件无法自动核对）。

历史教训：本脚本第一版把 pageRange 当成 PDF 页序，又因 sourceRef 已含 `content/`
前缀而重复拼接，导致 md 恒为空、对位检查一条未跑，却报出「0 处不符」。
现在 md 路径直接用 sourceRef，并把 PDF 页换算写成显式公式。
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
PDF_DIR = os.path.join(ROOT, 'source_data/pdf_sources')

try:
    import pymupdf
except ImportError:  # 无 PDF 库时仍做元数据一致性检查
    pymupdf = None


def norm(s):
    return re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', s or '')


def section_body(sec):
    """读节正文（跳过 YAML front matter），返回规范化后的前 30 字。"""
    ref = sec.get('sourceRef') or ''
    fp = os.path.join(ROOT, ref)
    if not os.path.exists(fp):
        return ''
    s = open(fp, encoding='utf-8').read()
    parts = s.split('---')
    if len(parts) >= 3:
        s = '---'.join(parts[2:])
    s = re.sub(r'(?m)^#+\s*', '', s)
    # 抽取时插入的图注标记会打乱与 PDF 原文的比对，先剔掉
    s = re.sub(r'配图|图表|见表|如图|插图', '', s)
    return norm(s)[:10]


def check_book_meta():
    """书级 index.md 的 totalPages / imageOffset 必须与 source_data/<book>/metadata.json 一致。

    totalPages 一旦漂移，rule 18 的判据就失效（曾出现 6 册被改成「印刷页数」或
    「最后一节结束页」），而 demo 又会把它当作「全书共 N 页」展示给读者。
    """
    problems = []
    for meta_path in sorted(glob.glob(os.path.join(ROOT, 'source_data/*/metadata.json'))):
        bid = os.path.basename(os.path.dirname(meta_path))
        try:
            meta = json.load(open(meta_path, encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        idx = glob.glob(os.path.join(ROOT, 'content/**/', bid, 'index.md'), recursive=True)
        if not idx:
            continue
        s = open(idx[0], encoding='utf-8').read()[:600]
        m_tp = re.search(r'totalPages:\s*(\d+)', s)
        m_io = re.search(r'imageOffset:\s*(\d+)', s)
        if not m_tp:
            problems.append(f'{bid}: index.md 缺 totalPages')
            continue
        if int(m_tp.group(1)) != meta.get('totalPages'):
            problems.append(f"{bid}: totalPages index={m_tp.group(1)} ≠ metadata={meta.get('totalPages')}")
        if m_io and meta.get('imageOffset') is not None and int(m_io.group(1)) != meta['imageOffset']:
            problems.append(f"{bid}: imageOffset index={m_io.group(1)} ≠ metadata={meta['imageOffset']}")
    return problems


def main():
    drift = check_book_meta()
    print(f'元数据一致性（index.md vs metadata.json）：{"✓ 全部一致" if not drift else f"✗ {len(drift)} 处不一致"}')
    for d in drift[:8]:
        print('   ' + d)

    if pymupdf is None:
        print('未安装 pymupdf，跳过 PDF 核对：pip3 install --user --break-system-packages pymupdf')
        return 1 if drift else 0

    g = json.load(open(os.path.join(ROOT, 'dist/graph.json'), encoding='utf-8'))
    books = {n['id']: n for n in g['nodes'] if n['type'] == 'Textbook'}
    secs = {}
    for n in g['nodes']:
        if n['type'] == 'Section' and n.get('pageRange'):
            secs.setdefault(n.get('textbookId'), []).append(n)

    missing_pdf, oob, mism, empty = [], [], [], 0
    sampled = hit = 0

    for bid, ss in secs.items():
        path = os.path.join(PDF_DIR, bid + '.pdf')
        if not os.path.exists(path):
            missing_pdf.append(bid)
            continue
        off = books.get(bid, {}).get('imageOffset') or 0
        doc = pymupdf.open(path)
        pages = doc.page_count
        mx = max(max(s['pageRange']) for s in ss) + off
        if mx > pages:
            oob.append((bid, mx, pages))

        # 首/中/末三处抽检：印刷页 + 偏移 = PDF 页
        picks = [ss[0], ss[len(ss) // 2], ss[-1]]
        for s in picks:
            head = section_body(s)
            if not head:
                continue
            sampled += 1
            p = s['pageRange'][0] + off
            if p < 1 or p > pages:
                continue
            txt = norm(doc[p - 1].get_text())
            if not txt:
                empty += 1
                continue
            if head in txt:
                hit += 1
            else:
                mism.append((bid, s['id'], s['pageRange'][0], p, head[:10]))
        doc.close()

    print(f'PDF 可用 {len(books) - len(missing_pdf)} / {len(books)} 册' + (f'，缺 {missing_pdf[:3]}' if missing_pdf else ''))
    print(f'页码越界 {len(oob)} 册' + ('' if not oob else f'：{oob[:3]}'))
    print(f'对位抽检 {hit}/{sampled} 命中（印刷页 + imageOffset → PDF 页）')
    for x in mism[:6]:
        print(f'   不符: {x[0]} {x[1]} 印刷 p.{x[2]} → PDF {x[3]} | md 开头 {x[4]}')
    if empty:
        print(f'抽到无文本层页 {empty} 处（扫描件，无法自动核对）')
    return 1 if (drift or oob) else 0


if __name__ == '__main__':
    sys.exit(main())
