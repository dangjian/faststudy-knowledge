#!/usr/bin/env python3
"""
将 content markdown 中的裸 LaTeX 公式包裹为 $...$。

策略（保守）：
1. 先 unwrap 已有行内 $...$（幂等）
2. 规范化 OCR LaTeX 语法
3. 只包裹「命令 + 紧邻数学符号」，禁止中文进入公式

用法:
  python wrap_latex_math.py [--dry-run] [path...]
默认处理 knowledge/content/八年级/上册 下含裸 LaTeX 的 md。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DEFAULT_ROOT = REPO / 'knowledge' / 'content' / '八年级' / '上册'

LATEX_HINT = re.compile(
    r'\\(?:frac|sqrt|dot|left|right|times|pm|approx|ge|le|neq|angle|pi|circ|cdot|div|text|infty|leq|geq|triangle|perp)'
)

PROTECT_RE = re.compile(r'(\$\$.*?\$\$|```[\s\S]*?```|`[^`]+`)', re.DOTALL)
CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

def is_ascii_alnum(ch: str) -> bool:
    return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z') or ('0' <= ch <= '9')


def is_ascii_digit(ch: str) -> bool:
    return '0' <= ch <= '9'


def is_ascii_alpha(ch: str) -> bool:
    return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


KNOWN_CMDS = frozenset({
    'frac', 'sqrt', 'left', 'right', 'cdot', 'times', 'div', 'pm', 'mp',
    'dot', 'ddot', 'approx', 'ge', 'le', 'neq', 'ne', 'angle', 'pi',
    'circ', 'text', 'textcircled', 'vec', 'overline', 'underline', 'hat',
    'tilde', 'bar', 'infty', 'leq', 'geq', 'sim', 'equiv', 'triangle',
    'perp', 'parallel', 'square', 'circled', 'omega', 'alpha', 'beta',
    'gamma', 'delta', 'theta', 'lambda', 'mu', 'sigma', 'phi', 'psi',
    'Omega', 'Delta', 'Sigma', 'mathrm', 'mathbf', 'mathbb', 'partial',
    'sum', 'prod', 'int', 'lim', 'sin', 'cos', 'tan', 'log', 'ln', 'exp',
    'cdots', 'ldots', 'dots', 'overline', 'underline',
})


def is_boundary(ch: str) -> bool:
    """公式不可跨越的边界字符。"""
    if not ch or ch.isspace():
        return False  # 空格单独处理
    if CJK_RE.match(ch):
        return True
    if ch in '*_`#~':
        return True
    # 中英文标点（含全角）
    if ch in '，。；：？！、""''「」『』（）【】《》…—·※':
        return True
    if '\uff00' <= ch <= '\uffef':
        return True
    return False


def skip_braced(s: str, i: int) -> int:
    if i >= len(s) or s[i] != '{':
        return i
    depth = 0
    j = i
    while j < len(s):
        if s[j] == '\\' and j + 1 < len(s):
            j += 2
            continue
        if s[j] == '{':
            depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(s)


def skip_bracketed(s: str, i: int) -> int:
    if i >= len(s) or s[i] != '[':
        return i
    j = i + 1
    while j < len(s) and s[j] != ']':
        j += 1
    return min(j + 1, len(s))


def consume_latex_cmd(s: str, i: int) -> int:
    if i >= len(s) or s[i] != '\\':
        return i
    j = i + 1
    if j >= len(s):
        return j
    if not is_ascii_alpha(s[j]):
        return j + 1
    while j < len(s) and is_ascii_alpha(s[j]):
        j += 1
    cmd = s[i + 1:j]

    while j < len(s) and s[j] in ' \t':
        if j + 1 < len(s) and s[j + 1] in '[{(':
            j += 1
            break
        break

    while j < len(s) and s[j] in ' \t':
        j += 1
    if j < len(s) and s[j] == '[':
        j = skip_bracketed(s, j)

    while j < len(s) and s[j] in ' \t':
        j += 1

    if cmd in ('left', 'right', 'bigl', 'bigr', 'Bigl', 'Bigr', 'big', 'Big', 'bigg', 'Bigg'):
        if j < len(s):
            if s[j] == '.':
                j += 1
            elif s[j] in '([{)|':
                j += 1
            elif s[j] == '\\':
                j = consume_latex_cmd(s, j)
        return j

    brace_count = 0
    if cmd == 'frac':
        brace_count = 2
    elif cmd in (
        'sqrt', 'dot', 'ddot', 'hat', 'tilde', 'bar', 'vec', 'overline',
        'underline', 'text', 'textcircled', 'mathrm', 'mathbf', 'mathbb',
        'circled', 'operatorname',
    ):
        brace_count = 1
    elif j < len(s) and s[j] == '{':
        brace_count = 1

    for _ in range(brace_count):
        while j < len(s) and s[j] in ' \t':
            j += 1
        if j < len(s) and s[j] == '{':
            j = skip_braced(s, j)
        elif cmd == 'sqrt':
            while j < len(s) and s[j] in ' \t':
                j += 1
            if j < len(s) and s[j] == '\\':
                j = consume_latex_cmd(s, j)
            elif j < len(s) and (is_ascii_alnum(s[j]) or s[j] == '-'):
                if s[j] == '-':
                    j += 1
                while j < len(s) and (is_ascii_alnum(s[j]) or s[j] == '.'):
                    j += 1
        else:
            break
    return j


def find_atomic_spans(s: str) -> list[tuple[int, int]]:
    """找出每个 LaTeX 命令或 a^{2} 原子的 [start, end)。"""
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\\':
            j = i + 1
            if j < n and is_ascii_alpha(s[j]):
                k = j
                while k < n and is_ascii_alpha(s[k]):
                    k += 1
                cmd = s[j:k]
                if cmd in KNOWN_CMDS or cmd.startswith('text'):
                    end = consume_latex_cmd(s, i)
                    spans.append((i, end))
                    i = end
                    continue
            elif j < n:
                spans.append((i, j + 1))
                i = j + 1
                continue
        if s[i] in '^_':
            j = i + 1
            while j < n and s[j] in ' \t':
                j += 1
            end = j
            if j < n and s[j] == '{':
                end = skip_braced(s, j)
                # 下标/上标含中文（如 _{甲}）不纳入公式原子
                if CJK_RE.search(s[j:end]):
                    i = end
                    continue
            elif j < n and is_ascii_alnum(s[j]):
                end = j + 1
            else:
                i += 1
                continue
            start = i
            # 基：左侧紧邻的标识符/数字/)/}
            if start > 0 and (is_ascii_alnum(s[start - 1]) or s[start - 1] in ')}'):
                start -= 1
                while start > 0 and is_ascii_alnum(s[start - 1]):
                    start -= 1
            spans.append((start, end))
            i = end
            continue
        i += 1
    return spans


def can_bridge(gap: str) -> bool:
    """两原子之间可否合并：允许空格、四则、等号、中间数字。"""
    if not gap:
        return True
    if CJK_RE.search(gap):
        return False
    if any(is_boundary(c) for c in gap if not c.isspace() and c not in '+-*/=.' and not is_ascii_digit(c)):
        return False
    return bool(re.fullmatch(r'[\s+\-*/=\d.]*', gap))


def expand_atom(s: str, start: int, end: int) -> tuple[int, int]:
    """向左右有限扩展：数字、小数、一元正负。"""
    # 左：越过空格连接到小数/整数（3.9 \dot{7}）
    # 但不连接到 \left/\right（避免页码 31\left(3\right)）
    cmd_after = re.match(r'\\([a-zA-Z]+)', s[start:])
    cmd_name = cmd_after.group(1) if cmd_after else ''
    if cmd_name not in ('left', 'right', 'bigl', 'bigr', 'Bigl', 'Bigr'):
        probe = start
        while probe > 0 and s[probe - 1].isspace():
            probe -= 1
        if probe > 0 and (is_ascii_digit(s[probe - 1]) or s[probe - 1] == '.'):
            start = probe
            while start > 0 and (is_ascii_digit(s[start - 1]) or s[start - 1] == '.'):
                start -= 1

    # 左：一元负号（\frac 前的负号）
    if start > 0 and s[start - 1] == '-' and (start == 1 or s[start - 2].isspace() or is_boundary(s[start - 2]) or s[start - 2] in '=('):
        start -= 1

    # 左：单字母变量 + 可选空格（s = 4.9 t^{2} 中的衔接由 bridge；此处处理 s= 紧贴）
    probe = start
    while probe > 0 and s[probe - 1].isspace():
        probe -= 1
    if probe > 0 and s[probe - 1] in '=+-*/':
        op = probe - 1
        q = op
        while q > 0 and s[q - 1].isspace():
            q -= 1
        if q > 0 and is_ascii_alpha(s[q - 1]) and (q == 1 or not is_ascii_alnum(s[q - 2])):
            start = q - 1

    # 右：= 数字 / = 单字母 / = 另一命令（由 merge 处理）
    while True:
        m = re.match(r'(\s*=\s*)(-?\d+(?:\.\d+)?|[a-zA-Z])(?![a-zA-Z])', s[end:])
        if not m:
            break
        end += m.end()

    while start < end and s[start].isspace():
        start += 1
    while end > start and s[end - 1].isspace():
        end -= 1
    return start, end


def merge_atoms(s: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    expanded = [expand_atom(s, a, b) for a, b in spans]
    expanded.sort()
    out = [expanded[0]]
    for a, b in expanded[1:]:
        pa, pb = out[-1]
        gap = s[pb:a]
        if can_bridge(gap):
            out[-1] = (pa, b)
        else:
            out.append((a, b))
    return out


def normalize_latex_ocr(text: str) -> str:
    # 修复被破坏的 \frac（form feed 等控制符）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]frac', r'\\frac', text)

    # 含中文的 \left(...) → 中文括号
    text = re.sub(
        r'\\left\s*\(([^)\\]*[\u4e00-\u9fff][^)\\]*)\\right\s*\)',
        r'（\1）',
        text,
    )
    text = re.sub(
        r'\\left\s*\(([^)\\]*[\u4e00-\u9fff][^)\\]*)\)',
        r'（\1）',
        text,
    )

    # OCR 残缺的 \left. {expr} \right) → 只保留 expr
    text = re.sub(r'\\left\.\s*\{([^{}]*)\}\s*\\right\.?', r'\1', text)
    text = re.sub(r'\\left\.\s*\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\left\.\s*', '', text)

    text = re.sub(r'\\sqrt\s*\[\s*(\d+)\s*\]\s*\{', r'\\sqrt[\1]{', text)
    text = re.sub(r'\\sqrt\s*\[\s*(\d+)\s*\]\s*-\s*(\d+(?:\.\d+)?)', r'\\sqrt[\1]{-\2}', text)
    text = re.sub(r'\\sqrt\s*\[\s*(\d+)\s*\]\s*([a-zA-Z]+)', r'\\sqrt[\1]{\2}', text)
    text = re.sub(r'\\sqrt\s*\[\s*(\d+)\s*\]\s*(\d+(?:\.\d+)?)', r'\\sqrt[\1]{\2}', text)
    text = re.sub(r'\\sqrt\s+(?!\{|\[)(-?\d+(?:\.\d+)?|[a-zA-Z]+)', r'\\sqrt{\1}', text)
    text = re.sub(r'\\sqrt\s*\{', r'\\sqrt{', text)

    text = re.sub(r'\^\s*\{\s*', '^{', text)
    text = re.sub(r'_\s*\{\s*', '_{', text)
    text = re.sub(r'\s+\^\s*', '^', text)
    text = re.sub(r'\s+_\s*', '_', text)

    text = re.sub(r'\\frac\s*\{', r'\\frac{', text)
    text = re.sub(r'\}\s*\{', '}{', text)

    text = re.sub(r'\\left\s*', r'\\left', text)
    text = re.sub(r'\\right\s*', r'\\right', text)
    text = re.sub(r'\\left\(\s+', r'\\left(', text)
    text = re.sub(r'\s+\\right\)', r'\\right)', text)
    text = re.sub(r'\\dot\s*\{', r'\\dot{', text)

    def clean_brace(m: re.Match) -> str:
        inner = m.group(1)
        if CJK_RE.search(inner):
            return '{' + inner.strip() + '}'
        if re.match(r'^[\d\s.]+$', inner):
            return '{' + inner.replace(' ', '') + '}'
        return '{' + inner.strip() + '}'

    for _ in range(3):
        text = re.sub(r'\{([^{}]+)\}', clean_brace, text)

    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)

    return text


def unwrap_inline_math(text: str) -> str:
    blocks: list[str] = []

    def save_block(m: re.Match) -> str:
        blocks.append(m.group(0))
        return f'\x00BLOCK{len(blocks) - 1}\x00'

    text = re.sub(r'\$\$.*?\$\$', save_block, text, flags=re.DOTALL)
    # 反复去掉行内 $，直到稳定（处理异常嵌套）
    for _ in range(5):
        new = re.sub(r'\$([^$\n]+)\$', r'\1', text)
        if new == text:
            break
        text = new
    # 残留的单独 $
    text = text.replace('$', '')
    for i, b in enumerate(blocks):
        text = text.replace(f'\x00BLOCK{i}\x00', b)
    return text


def demote_unpaired_leftright(chunk: str) -> str:
    # 先删掉无分隔符的 \left/\right（避免 KaTeX Expected group）
    chunk = re.sub(r'\\left(?!\s*(?:[(\[\{.|]|\\[a-zA-Z]+))', '', chunk)
    chunk = re.sub(r'\\right(?!\s*(?:[)\]\}.|]|\\[a-zA-Z]+))', '', chunk)
    if chunk.count('\\left') == chunk.count('\\right'):
        return chunk
    chunk = re.sub(r'\\left(\.|\(|\[|\{|\|)', lambda m: '' if m.group(1) == '.' else m.group(1), chunk)
    chunk = re.sub(r'\\right(\.|\)|\]|\}|\|)', lambda m: '' if m.group(1) == '.' else m.group(1), chunk)
    return chunk


def wrap_math_in_segment(segment: str) -> str:
    if '\\' not in segment and '^{' not in segment and '_{' not in segment:
        return segment

    spans = merge_atoms(segment, find_atomic_spans(segment))
    if not spans:
        return segment

    out = segment
    for a, b in reversed(spans):
        chunk = out[a:b]
        if not chunk or '\\' not in chunk and '^{' not in chunk and '_{' not in chunk:
            continue
        # 硬性拒绝：含中文的不包裹
        if CJK_RE.search(chunk):
            continue
        chunk = demote_unpaired_leftright(chunk)
        if not chunk:
            continue
        out = out[:a] + '$' + chunk + '$' + out[b:]
    return out


def wrap_latex_math(text: str) -> str:
    text = unwrap_inline_math(text)
    text = normalize_latex_ocr(text)

    parts = PROTECT_RE.split(text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            result.append('\n'.join(wrap_math_in_segment(line) for line in part.split('\n')))
    return ''.join(result)


def process_file(path: Path, dry_run: bool = False) -> bool:
    original = path.read_text(encoding='utf-8')
    if not LATEX_HINT.search(original) and '^{' not in original and '$' not in original:
        return False

    if original.startswith('---'):
        parts = original.split('---', 2)
        if len(parts) >= 3:
            new_text = f'---{parts[1]}---{wrap_latex_math(parts[2])}'
        else:
            new_text = wrap_latex_math(original)
    else:
        new_text = wrap_latex_math(original)

    if new_text == original:
        return False
    if not dry_run:
        path.write_text(new_text, encoding='utf-8')
    return True


def collect_targets(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        for p in root.rglob('*.md'):
            try:
                text = p.read_text(encoding='utf-8')
            except OSError:
                continue
            if LATEX_HINT.search(text) or '^{' in text or '$' in text:
                files.append(p)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description='Wrap bare LaTeX in $...$')
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    roots = args.paths or [DEFAULT_ROOT]
    roots = [p if p.is_absolute() else REPO / p for p in roots]
    targets = collect_targets(roots)
    print(f'候选文件: {len(targets)}')

    changed = 0
    for path in targets:
        if process_file(path, dry_run=args.dry_run):
            changed += 1
            rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
            print(f'  {"[dry] " if args.dry_run else ""}✓ {rel}')

    print(f'{"将修改" if args.dry_run else "已修改"}: {changed}/{len(targets)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
