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
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
PDF_DIR = os.path.join(ROOT, 'source_data/pdf_sources')

try:
    import pymupdf
except ImportError:
    print('需要 pymupdf：pip3 install --user --break-system-packages pymupdf')
    sys.exit(1)


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


def main():
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


if __name__ == '__main__':
    main()
