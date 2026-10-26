#!/usr/bin/env python3
"""residual_scan.py — 节级字符余量核对（kg-repair 验收第 5.5 步）

对指定书的每节：取其 pageRange 页的 OCR 缓存行，逐行与节 md 正文做 2-gram 覆盖比对，
输出「OCR 有而正文无」的余量行及缺失字符。用于捕捉双栏重排/图注重组时的拼接丢字。

用法:
  python3 tools/kg/scripts/residual_scan.py <BookId> [--minlen 6] [--json OUT]

判定说明:
  - 页眉脚/页码行自动过滤（人民教育出版社变体含乱码、N道德与法治八年级上册、第X单元…页码）
  - 乱码行先尝试 GBK→UTF8 逐行恢复，失败则标记 [mojibake] 跳过
  - 余量行需人工定谳: 真实丢字 / OCR 形近噪声(md 为正确字) / 图内文字 / 页脚漏滤
"""
import re
import sys
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[3]
CACHE = ROOT / 'tools/kg/state/verify/cache'
CONTENT = ROOT / 'content'

FOOTER_PAT = re.compile(
    r'^(人民.{0,2}教育出.{0,2}社|道德与法治八年级[上下]册|'
    r'第[一二三四]单元\S{0,12}\d{1,3}|\d{1,3}道德与法治八年级[上下]册|.{0,3}\d{1,3})$'
)
CJK = re.compile(r'[\u4e00-\u9fff0-9A-Za-z]')
MOJI_HINT = re.compile(r'[浜鐐滀娴犺绱犲吇鍑虹増绀鎺㈢┒涓庡垎缁撳悎瀹炰緥鏍戠珛]')


def norm(s: str) -> str:
    return ''.join(CJK.findall(s))


def grams(s: str, n=2):
    return Counter(s[i:i + n] for i in range(len(s) - n + 1)) if len(s) >= n else Counter([s] if s else [])


def recover(line: str) -> str:
    try:
        rec = line.encode('gbk').decode('utf-8')
        if '\ufffd' not in rec and len(rec) > 2:
            return rec
    except Exception:
        pass
    return line


def load_md(md_path: pathlib.Path):
    t = md_path.read_text()
    # 仅剥开头 frontmatter（一对 ---）
    body = re.sub(r'\A---\n.*?\n---\n', '', t, flags=re.S)
    # 掐掉文末派生区块：L1 保留区块名（AGENTS.md：汉字/单词/短语/句子/插图/解题模型/笔记/总结）
    # 注意不能按首个 \n---\n 掐——正文中部 --- 分隔（预习/科学阅读块）会误掐制造大量假阳
    tail = re.search(r'\n## (?:汉字|单词|短语|句子|插图|解题模型|笔记|总结)\b', body)
    if tail:
        body = body[:tail.start()]
    return norm(body)


def detect_offset(book: str):
    """按页脚印刷页码投票探测 PDF页=印刷页+off 的偏移。"""
    cache = CACHE / book
    votes = Counter()
    for f in cache.glob('p*.txt'):
        try:
            n = int(f.stem[1:])
        except ValueError:
            continue
        lines = [l.strip() for l in f.read_text().splitlines() if l.strip()]
        for l in lines[-2:]:
            for m in re.finditer(r'(?<!\d)(\d{1,3})(?!\d)', l):
                num = int(m.group(1))
                off = n - num
                if 0 <= off <= 30:
                    votes[off] += 1
    if not votes:
        return None
    off, cnt = votes.most_common(1)[0]
    return off if cnt >= 5 else None


def main():
    book = sys.argv[1]
    minlen = 6
    json_out = None
    args = sys.argv[2:]
    if '--minlen' in args:
        minlen = int(args[args.index('--minlen') + 1])
    if '--json' in args:
        json_out = args[args.index('--json') + 1]

    offset = detect_offset(book)
    secs = sorted(CONTENT.rglob(f'**/{book}/chapters/*/sections/S*.md'))
    report = []
    total_res = 0
    for md in secs:
        t = md.read_text()
        m = re.search(r'pageRange:\s*\[(\d+),\s*(\d+)\]', t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        else:
            m2 = re.search(r'pageRange:\s*\n\s*-\s*(\d+)\s*\n\s*-\s*(\d+)', t)
            if not m2:
                continue
            a, b = int(m2.group(1)), int(m2.group(2))
        # PDF 页 = 印刷页 + 偏移; 通过探测: 找缓存里存在的页。先按 +7 假设,再回退探测
        mdtext = load_md(md)
        residuals = []
        for printed in range(a, b + 1):
            pdf = printed + (offset if offset is not None else 7)
            f = CACHE / book / f'p{pdf}.txt'
            if not f.exists():
                continue
            for raw in f.read_text().splitlines():
                line = raw.strip()
                if not line or FOOTER_PAT.match(line):
                    continue
                if MOJI_HINT.search(line) and '人民' not in line:
                    line = recover(line)
                nline = norm(line)
                if len(nline) < minlen:
                    continue
                og, mg = grams(nline), grams(mdtext)
                missing = og - mg
                cov = 1 - sum(missing.values()) / max(1, sum(og.values()))
                if cov < 0.999:
                    miss_chars = ''.join(sorted({g for g in missing.elements()}))
                    residuals.append({'page': pdf, 'printed': printed, 'line': line,
                                      'cov': round(cov, 2), 'miss': miss_chars[:30]})
        total_res += len(residuals)
        report.append({'sec': str(md.relative_to(CONTENT)), 'residuals': residuals})

    for r in report:
        if r['residuals']:
            print(f"\n=== {r['sec']} ({len(r['residuals'])} 条余量) ===")
            for x in r['residuals']:
                print(f"  p{x['page']}(印{x['printed']}) cov={x['cov']} 缺[{x['miss']}] {x['line'][:60]}")
    print(f"\ntotal sections={len(report)} residual lines={total_res} offset={offset}")
    if json_out:
        pathlib.Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
