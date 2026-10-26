#!/usr/bin/env python3
"""
统一清理 knowledge content 中的结构/公式问题：

1. 标题与正文粘连：`### 3. 二次根式 观察…` → 标题单独成行
2. 残缺 LaTeX：`\\left` 无括号、条件被截断等，避免 KaTeX ParseError
3. 常见 OCR 条件残留：`，$\\ge$ 0，b $\\ge$ 0)` → `（$a \\ge 0$，$b \\ge 0$）`

用法:
  python sanitize_prose.py [--dry-run] [path...]
默认处理 knowledge/content/八年级/上册/数学
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DEFAULT_ROOT = REPO / 'knowledge' / 'content' / '八年级' / '上册' / '数学'

CJK = re.compile(r'[\u4e00-\u9fff]')

# 节标题后正文常见起手
BODY_START = re.compile(
    r'(?=如图|观察|在一个|在一|一般地|把一个|把一|为了|前面我们|如果一个|如果|'
    r'已知|分别是|二次根式也可以|从电线|图\d|夜幕|阳光|实践与练习|'
    r'实验与记录|读一读|想一想|雾和露|长江是|人耳只能|光射到|'
    r'比较物体|如何测量|先、|2\.观察|2\.在水温)'
)

# 数学节标题：### 1. xxx / ## 第x章
HEADING_LINE = re.compile(r'^(#{2,3})\s+(.+)$')


def split_glued_heading(line: str) -> list[str]:
    """若标题与正文粘在同一行，拆成两行。"""
    m = HEADING_LINE.match(line)
    if not m:
        return [line]
    hashes, rest = m.group(1), m.group(2).strip()

    # 已是短标题（无正文）
    if len(rest) <= 24 and not BODY_START.search(' ' + rest):
        return [line]

    # ### 1. 标题正文… 或 ### 第1课 标题正文…
    # 先尝试数字节标题
    m2 = re.match(
        r'^(\d+\.\s*[\u4e00-\u9fffA-Za-z0-9（）()]{1,30}?)(?=\s|$)(.*)$',
        rest,
    )
    if m2:
        title, body = m2.group(1).strip(), m2.group(2).strip()
        # 用 BODY_START 在 title+body 里找更准的切分
        combined = title + (' ' + body if body else '')
        # 在 combined 上找正文起手；标题最多取到起手之前
        bm = BODY_START.search(combined)
        if bm and bm.start() > 0:
            title = combined[:bm.start()].strip()
            body = combined[bm.start():].strip()
        elif body:
            # 无明确起手：标题取前 2–12 个汉字词段
            tm = re.match(
                r'^(\d+\.\s*[\u4e00-\u9fffA-Za-z0-9（）()?！]{2,20})(.*)$',
                combined,
            )
            if tm and tm.group(2).strip():
                title, body = tm.group(1).strip(), tm.group(2).strip()
            else:
                return [line]
        else:
            return [line]

        if body and title:
            return [f'{hashes} {title}', '', body]
        return [line]

    # ### 第N课/节 标题 + 正文
    m3 = re.match(
        r'^((?:第[一二三四五六七八九十百零\d]+[课章节节]|[一二三四五六七八九十]+、)'
        r'[\u4e00-\u9fffA-Za-z0-9（）()、]{0,40}?)(?=\s|$)(.*)$',
        rest,
    )
    if m3:
        title, body = m3.group(1).strip(), m3.group(2).strip()
        combined = title + (' ' + body if body else '')
        bm = BODY_START.search(combined)
        if bm and bm.start() > 3:
            title = combined[:bm.start()].strip()
            body = combined[bm.start():].strip()
        # 去掉标题里误粘的页眉分隔 |
        title = re.sub(r'\|.*$', '', title).strip()
        if body and len(title) >= 2:
            return [f'{hashes} {title}', '', body]

    return [line]


def sanitize_math_chunk(chunk: str) -> str | None:
    """清理单个 $...$ 内的非法 LaTeX。返回 None 表示整段删掉定界符改回纯文本。"""
    s = chunk

    # 删除无分隔符的 \left / \right（KaTeX: Expected group as argument to '\left'）
    s = re.sub(r'\\left(?!\s*(?:[(\[\{.|]|\\[a-zA-Z]+))', '', s)
    s = re.sub(r'\\right(?!\s*(?:[)\]\}.|]|\\[a-zA-Z]+))', '', s)

    # 成对校验：不成对则降级为普通括号
    if s.count('\\left') != s.count('\\right'):
        s = re.sub(r'\\left(\.|\(|\[|\{|\|)', lambda m: '' if m.group(1) == '.' else m.group(1), s)
        s = re.sub(r'\\right(\.|\)|\]|\}|\|)', lambda m: '' if m.group(1) == '.' else m.group(1), s)

    # 空 chunk / 只剩空白或孤立算符
    s = s.strip()
    if not s or s in {'=', '+', '-', ',', '，', '.', '·'}:
        return None

    # 仍含明显非法：行末 \left、\right
    if re.search(r'\\left\s*$|\\right\s*$', s):
        s = re.sub(r'\\left\s*$|\\right\s*$', '', s).strip()
        if not s:
            return None

    # 花括号大致平衡（忽略 \{ \}）
    def brace_balance(t: str) -> bool:
        depth = 0
        i = 0
        while i < len(t):
            if t[i] == '\\' and i + 1 < len(t) and t[i + 1] in '{}':
                i += 2
                continue
            if t[i] == '{':
                depth += 1
            elif t[i] == '}':
                depth -= 1
                if depth < 0:
                    return False
            i += 1
        return depth == 0

    if not brace_balance(s):
        # 尝试丢掉多余尾部 }
        while s.endswith('}') and not brace_balance(s):
            s = s[:-1].rstrip()
        if not brace_balance(s) or not s:
            return None

    return s


def sanitize_all_math(text: str) -> str:
    """处理行内与块级数学。"""

    def repl_inline(m: re.Match) -> str:
        inner = sanitize_math_chunk(m.group(1))
        if inner is None:
            return m.group(1)  # 去掉 $，保留文本
        return f'${inner}$'

    def repl_block(m: re.Match) -> str:
        inner = sanitize_math_chunk(m.group(1))
        if inner is None:
            return ''
        return f'$$\n{inner}\n$$'

    # 先块级
    text = re.sub(r'\$\$([\s\S]*?)\$\$', repl_block, text)
    text = re.sub(r'\$([^$\n]+)\$', repl_inline, text)
    return text


def fix_condition_remnants(text: str) -> str:
    """修复被截断的定义域条件。"""
    # ，$\ge$ 0，b $\ge$ 0) 或 ，$\ge$ 0， b $\ge$ 0)
    text = re.sub(
        r'，\s*\$\\ge\$\s*0\s*，\s*b\s*\$\\ge\$\s*0\s*\)',
        r'（$a \\ge 0$，$b \\ge 0$）',
        text,
    )
    # b $\ge$ 0)， 0 ，b $\ge$ 0)
    text = re.sub(
        r'，?\s*b\s*\$\\ge\$\s*0\s*\)\s*，?\s*0\s*，\s*b\s*\$\\ge\$\s*0\s*\)',
        r'（$a \\ge 0$，$b \\ge 0$）',
        text,
    )
    # ， b > 041 / ， b > 0) 页码粘连
    text = re.sub(r'，\s*b\s*>\s*0\d+', r'，$b > 0$', text)
    text = re.sub(r'，\s*b\s*>\s*0\s*\)', r'，$b > 0$', text)

    # 孤立的 `，$\ge$ 0` 且前后像公式条件
    text = re.sub(
        r'\$\\sqrt\{a\s*b\}\$\s*，\s*\$\\ge\$\s*0',
        r'$\\sqrt{ab}$（$a \\ge 0$',
        text,
    )

    # `\left` 残留在正文（不在 $ 内）
    text = re.sub(r'\\left(?!\s*[(\[\{.\\])', '', text)
    text = re.sub(r'\\right(?!\s*[)\]\}.\\])', '', text)

    # 页码粘在段落末尾：汉字/标点后的独立 2 位数字行尾
    text = re.sub(r'([。？！…])\s*\d{1,2}\s*$', r'\1', text, flags=re.M)

    # 错误的 —$. 之类
    text = re.sub(r'=\s*—\s*\$\s*\.', r'=', text)
    text = re.sub(r'=\—\$', r'=', text)

    return text


def fix_item_left_right(text: str) -> str:
    """把题号 $\\left(1\\right)$ 改成普通 (1)，减少噪音。"""
    text = re.sub(r'\$\\left\((\d+)\\right\)\$', r'(\1)', text)
    text = re.sub(r'\$\\left\((\d+)\\right\)\s+', r'(\1) $', text)
    return text


def demote_false_headings(line: str) -> str:
    """把误标成标题的习题/长句降级为正文。"""
    m = re.match(r'^(#{2,3})\s+(\d+\.\s*)(.+)$', line)
    if not m:
        m = re.match(r'^(#{2,3})(\d+\.\s*)(.+)$', line)
        if not m:
            return line
        hashes, num, rest = m.group(1), m.group(2), m.group(3)
    else:
        hashes, num, rest = m.group(1), m.group(2), m.group(3)

    rest_s = rest.strip()
    # 去掉标题末尾误切的单字（在/把/为/将/从…）
    rest_s = re.sub(r'\s+[在把为将从由对关于]$', '', rest_s).strip()

    false_starts = (
        '如图', '设', '当', '一组', '过直线', '为什么', '求这', '求下列',
        '根据', '分别是', '不描出', '假设', '在拟订', '哪个', '将图',
        '关于x', '关于y', '快速', '填充',
    )
    if (
        len(rest_s) > 16
        or any(rest_s.startswith(s) for s in false_starts)
        or rest_s.startswith('如图')
        or '？' in rest_s
        or '?' in rest_s
        or '$' in rest_s
    ):
        # 极短且像真实节名的例外：二次根式、认识证明…
        if re.fullmatch(r'[\u4e00-\u9fff]{2,10}', rest_s) and not any(
            rest_s.startswith(s) for s in false_starts
        ):
            return f'{hashes} {num}{rest_s}'
        return f'**{num}{rest_s}**'

    return f'{hashes} {num}{rest_s}'


def process_text(text: str) -> str:
    lines = text.split('\n')
    out: list[str] = []
    for line in lines:
        for part in split_glued_heading(line):
            out.append(demote_false_headings(part) if part.startswith('#') else part)
    text = '\n'.join(out)
    text = sanitize_all_math(text)
    text = fix_condition_remnants(text)
    text = fix_item_left_right(text)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text


def process_file(path: Path, dry_run: bool = False) -> bool:
    original = path.read_text(encoding='utf-8')
    if original.startswith('---'):
        parts = original.split('---', 2)
        if len(parts) >= 3:
            new_text = f'---{parts[1]}---{process_text(parts[2])}'
        else:
            new_text = process_text(original)
    else:
        new_text = process_text(original)

    if new_text == original:
        return False
    if not dry_run:
        path.write_text(new_text, encoding='utf-8')
    return True


def collect(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(sorted(root.rglob('*.md')))
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*', type=Path)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    roots = [p if p.is_absolute() else REPO / p for p in (args.paths or [DEFAULT_ROOT])]
    targets = collect(roots)
    changed = 0
    for p in targets:
        if process_file(p, dry_run=args.dry_run):
            changed += 1
            rel = p.relative_to(REPO) if p.is_relative_to(REPO) else p
            print(f'  {"[dry] " if args.dry_run else ""}✓ {rel}')
    print(f'{"将修改" if args.dry_run else "已修改"}: {changed}/{len(targets)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
