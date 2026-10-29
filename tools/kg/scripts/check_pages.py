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


def hans(s):
    """只保留汉字。

    一年级等册的 PDF 文本层带拼音注音（「我w们men知zh道do」），若把拉丁字母
    也算进指纹，md 的连续子串在 PDF 里结构上永远匹配不上——2026-10-29 审计
    发现旧判据因此把 78% 的样本误报成「不符」。
    """
    return re.sub(r'[^\u4e00-\u9fa5]', '', s or '')


def section_body(sec):
    """读节正文（跳过 front matter、去掉标题行），返回前 40 个汉字。"""
    ref = sec.get('sourceRef') or ''
    fp = os.path.join(ROOT, ref)
    if not os.path.exists(fp):
        return ''
    s = open(fp, encoding='utf-8').read()
    parts = s.split('---')
    if len(parts) >= 3:
        s = '---'.join(parts[2:])
    s = re.sub(r'(?m)^#+\s*.*$', '', s)       # 整行删除标题（标题与正文在 PDF 里常不连续）

    # 抽取时插入的图注标记会打乱与 PDF 原文的比对，先剔掉
    s = re.sub(r'配图|图表|见表|如图|插图', '', s)
    return hans(s)[:40]


def bigrams(t):
    return {t[i:i + 2] for i in range(len(t) - 1)}


def hit_ratio(head, txt):
    """md 正文与 PDF 页文本的汉字 bigram 重合率。

    不用「连续子串」：md 的正文是跨页合并的，标题与正文之间、页与页之间都
    不连续；带拼音注音的册更是整段插入了拉丁字母。bigram 重合率对这两类
    差异都容忍，同时仍能识别「页码指到了完全无关的页」。
    """
    hb = bigrams(head)
    if not hb:
        return 0.0
    return len(hb & bigrams(txt)) / len(hb)


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
    no_text = 0          # 有图无文本层（扫描件），无法对位
    no_offset = []       # 缺 imageOffset 的册：换算基准缺失时不再按 0 兜底
    sampled = hit = 0

    for bid, ss in secs.items():
        path = os.path.join(PDF_DIR, bid + '.pdf')
        if not os.path.exists(path):
            missing_pdf.append(bid)
            continue
        if 'imageOffset' not in books.get(bid, {}):
            no_offset.append(bid)
            continue
        off = books[bid]['imageOffset']
        doc = pymupdf.open(path)
        pages = doc.page_count
        mx = max(max(s['pageRange']) for s in ss) + off
        if mx > pages:
            oob.append((bid, mx, pages))

        # 首/中/末三处抽检（去重：单节/双节册否则会重复计入分母）
        picks = list({s['id']: s for s in (ss[0], ss[len(ss) // 2], ss[-1])}.values())
        for s in picks:
            head = section_body(s)
            if not head:
                continue
            sampled += 1
            p = s['pageRange'][0] + off
            if p < 1 or p > pages:
                continue
            page = doc[p - 1]
            raw = page.get_text()
            if not raw.strip():
                # 文本层空：再看墨量，判定是真空白还是扫描图
                pix = page.get_pixmap(dpi=40)
                smp = pix.samples
                tot = max(1, len(range(0, len(smp), 3 * 11)))
                ink = sum(1 for i in range(0, len(smp), 3 * 11)
                          if smp[i] < 245 or smp[i + 1] < 245 or smp[i + 2] < 245) / tot
                if ink < 0.02:
                    empty += 1
                else:
                    no_text += 1
                continue
            ph = hans(raw)
            if len(ph) < 30:
                no_text += 1      # 文本层过于稀疏（OCR 碎片），无法判定而非不符
                continue
            if hit_ratio(head, ph) >= 0.5:
                hit += 1
            else:
                mism.append((bid, s['id'], s['pageRange'][0], p, head[:10]))
        doc.close()

    print(f'PDF 可用 {len(books) - len(missing_pdf)} / {len(books)} 册' + (f'，缺 {missing_pdf[:3]}' if missing_pdf else ''))
    print(f'页码越界 {len(oob)} 册' + ('' if not oob else f'：{oob[:3]}'))
    if no_offset:
        print(f'缺 imageOffset 跳过 {len(no_offset)} 册：{no_offset[:3]}')
    checked = hit + len(mism)
    ratio = len(mism) / checked if checked else 0.0
    print(f'对位抽检 {hit}/{checked} 命中（不符 {ratio * 100:.0f}%，抽 {sampled} 处）')
    for x in mism[:6]:
        print(f'   不符: {x[0]} {x[1]} 印刷 p.{x[2]} → PDF {x[3]} | md 开头 {x[4]}')
    if empty:
        print(f'真空白页 {empty} 处')
    if no_text:
        print(f'有图无文本层 {no_text} 处（扫描件，无法自动核对）')

    failed = bool(drift or oob) or ratio > 0.3
    if ratio > 0.3:
        print(f'✗ 不符比例 {ratio * 100:.0f}% 超过 30% 阈值，判为失败')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
