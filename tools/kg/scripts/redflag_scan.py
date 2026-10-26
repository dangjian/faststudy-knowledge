#!/usr/bin/env python3
"""redflag_scan.py — content 节红旗机械扫描（kg-repair Step 1 定位工具）。

特征集（L1/L3 检测统一入口；含 scan_format_residue 并入的残渣模式）：
  机器占位H1 / H1纯栏目 / H1含续 / 句中开头 / 页脚残留 / 多课头 / 字表错挂 /
  版权页脚 / 密度异常 / pageRange 越界

用法（knowledge 仓根目录）：
  python3 tools/kg/scripts/redflag_scan.py                # 全仓
  python3 tools/kg/scripts/redflag_scan.py --book PEP-8-1-History
  python3 tools/kg/scripts/redflag_scan.py --book X --json out.json

输出：每文件一行红旗清单；--json 落盘结构化结果。
注意：密度特征对英语册与小学册自动白名单（词表/配图页密集属常态）。
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # knowledge/
CONTENT = os.path.join(ROOT, 'content')
GRAD_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
COLS = {'阅读', '写作', '口语交际', '综合性学习', '课外古诗词诵读', '名著导读', '专题学习活动',
        '活动课', '单元', '整本书阅读', '读读写写', '课后活动'}
FOOT_PAT = re.compile(r'^(\d{1,3}\s*[|丨]\s*\S{1,8}|\S{1,8}\s*[|丨]\s*\d{1,3}|·\s*\d{1,3}\s*·)$')


def book_id_of(book_dir):
    return os.path.basename(book_dir)


def is_primary(bid):
    m = re.match(r'[A-Z]+-(\d)-', bid)
    return m is not None and int(m.group(1)) <= 6


def scan_file(path, bid, dense_wl, canonical=None):
    flags = []
    try:
        c = open(path, encoding='utf-8').read()
    except Exception as e:
        return ['读取失败:%s' % e]
    fm = c.split('---')[1] if c.startswith('---') else ''
    body = c.split('---', 2)[2] if c.startswith('---') else c
    lines = body.split('\n')
    text = [l for l in lines if not l.startswith('|') and not l.startswith('<!--')]
    h1 = [l for l in lines if l.startswith('# ')]
    h1t = h1[0][2:].strip() if h1 else ''
    if re.match(r'^第\d+章.*[-－]第\d+节$', h1t):
        flags.append('机器占位H1')
    if h1t in COLS and h1t != (canonical or ''):
        flags.append('H1纯栏目')
    if re.search(r'（续）|\(续\)$', h1t):
        flags.append('H1含续')
    firsts = [l.strip() for l in text if l.strip()]
    if firsts and firsts[0] and firsts[0][0] in '，。；：、）】》？！' and not firsts[0].startswith('#'):
        flags.append('句中开头')
    for l in text:
        s = l.strip()
        if not s:
            continue
        if FOOT_PAT.match(s):
            flags.append('页脚残留')
            break
        if '仅供个人学习使用' in s:
            flags.append('版权页脚')
            break
        if len(s) <= 20 and '出版社' in s and '（配图' not in s and '①' not in s:
            flags.append('页脚残留')
            break
    if len(h1) > 1:
        flags.append('多课头%d' % len(h1))
    # —— 残渣模式（自 scan_format_residue.py 并入；2026-10-15 学科限定：
    #    坐标轴碎片/单字母/孤立图注/书眉行 仅人文社科启用——数学/科学/地理册的
    #    裸数字行、公式变量、图注独立行是内容固有形态，误报率高）——
    hum = ('Chinese' in bid) or ('History' in bid) or ('Politics' in bid)
    if hum:
        for l in text:
            sl = l.strip()
            if not sl or sl in ('---', '***', '___'):
                continue  # 正文水平分隔线合法
            if re.match(r'^[\-–—\d xyXY〇]{1,20}$', sl) and len(sl) >= 2:
                flags.append('坐标轴碎片'); break
            if re.match(r'^[A-Za-z]{1,2}$', sl):
                flags.append('单字母'); break
            if re.match(r'^图\s*[\d\-\.]+\s*$', sl):
                flags.append('孤立图注'); break
            if re.match(r'^第[一二三四五六七八九十\d]+[章单元].{0,2}[一—–\-丨|].{0,15}$', sl):
                flags.append('书眉行'); break
    if text and text[-1].strip() in ('---', '***'):
        flags.append('尾部分隔线')
    sid_m = re.search(r'sectionId:\s*(\S+)', fm)
    sid = sid_m.group(1) if sid_m else ''
    for l in lines:
        m = re.match(r'^\|\s*character:\S*?-([A-Z]\d+-S\d+):', l)
        if m and sid and not sid.endswith('-' + m.group(1)):
            flags.append('字表错挂')
            break
    pm = re.search(r'pageRange:\s*\[?\s*(\d+)\s*,\s*(\d+)', fm)
    if pm:
        a, b = int(pm.group(1)), int(pm.group(2))
        if b < a:
            flags.append('pageRange倒置')
        n = max(1, b - a + 1)
        den = len(''.join(text)) // n
        if den > 900 and not dense_wl:
            flags.append('密度高%d' % den)
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book', default=None, help='BookId，缺省全仓')
    ap.add_argument('--json', default=None, help='结构化结果落盘路径')
    args = ap.parse_args()

    results = []
    if args.book:
        # 直接定位该册目录
        hits = []
        for root, dirs, fs in os.walk(CONTENT):
            if book_id_of(root) == args.book and 'chapters' in dirs:
                hits.append(root)
        if not hits:
            print('book not found: %s' % args.book, file=sys.stderr)
            sys.exit(2)
        books = [(args.book, hits[0])]
    else:
        books = []
        for grade in sorted(os.listdir(CONTENT)):
            gp = os.path.join(CONTENT, grade)
            if not os.path.isdir(gp) or grade == 'wiki':
                continue
            for vol in sorted(os.listdir(gp)):
                vp = os.path.join(gp, vol)
                if not os.path.isdir(vp):
                    continue
                for subj in sorted(os.listdir(vp)):
                    sp = os.path.join(vp, subj)
                    if not os.path.isdir(sp):
                        continue
                    for bk in sorted(os.listdir(sp)):
                        bp = os.path.join(sp, bk)
                        if os.path.isdir(os.path.join(bp, 'chapters')):
                            books.append((bk, bp))

    # 书级 canonical 标题表（H1纯栏目 误报豁免：H1==canonical 即栏目名即课名）
    canonical_map = {}
    for bid, bp in books:
        try:
            cur_c = cur_s = None
            for l in open(os.path.join(bp, 'index.md'), encoding='utf-8'):
                m = re.match(r'\s*- id: (C\d+)\s*$', l)
                if m:
                    cur_c = m.group(1); cur_s = None
                    continue
                m = re.match(r'\s*- id: (S\d+)\s*$', l)
                if m:
                    cur_s = m.group(1)
                    continue
                m = re.match(r'\s*title: (.+?)\s*$', l)
                if m and cur_c and cur_s:
                    canonical_map['%s/%s' % (cur_c, cur_s)] = m.group(1).strip()
                    cur_s = None
        except Exception:
            pass

    for bid, bp in books:
        dense_wl = ('English' in bid) or is_primary(bid)
        ch_dir = os.path.join(bp, 'chapters')
        for ch in sorted(os.listdir(ch_dir)):
            secs = os.path.join(ch_dir, ch, 'sections')
            files = [os.path.join(secs, f) for f in sorted(os.listdir(secs))] if os.path.isdir(secs) else [os.path.join(ch_dir, ch, 'index.md')]
            for fp in files:
                flags = scan_file(fp, bid, dense_wl, canonical=canonical_map.get('%s/%s' % (ch, os.path.basename(fp)[:-3])))

                if flags:
                    rel = '%s/%s' % (ch, os.path.basename(fp)[:-3] if fp.endswith('.md') else 'index')
                    results.append({'book': bid, 'f': rel, 'flags': flags})

    # 已裁决登记抑制（adjudicated-flags.json）：book+file+flag前缀 匹配即不重报
    adjp = os.path.join(ROOT, 'tools/kg/state/verify/repair/adjudicated-flags.json')
    adj = json.load(open(adjp, encoding='utf-8')) if os.path.exists(adjp) else []
    kept = []
    for r in results:
        hit_adj = any(a['book'] == r['book'] and a['file'] == r['f'] and
                      any(r['flags'] and fl.startswith(a['flag']) for fl in r['flags'])
                      for a in adj)
        (kept if not hit_adj else []).append(r)
    results = kept
    for r in results:
        print(r['book'], r['f'], ','.join(r['flags']))
    print('total: %d flags / %d books' % (len(results), len(set(r['book'] for r in results))), file=sys.stderr)
    if args.json:
        json.dump(results, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


if __name__ == '__main__':
    main()
