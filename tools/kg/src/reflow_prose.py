#!/usr/bin/env python3
"""
整理 OCR 长段落正文版式（幂等）：

1. 去掉中文间误插空格（保留标题内空格）
2. 模块标记 / 例 / 解 / 习题 独立成段
3. 大题号、小题号换行
4. 清理页码粘连与破损加粗

用法:
  python reflow_prose.py [--dry-run] [path...]
默认: 八年级上册数学各章 index.md
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DEFAULT_ROOT = REPO / 'knowledge' / 'content' / '八年级' / '上册' / '数学'

MARKERS = [
    '阅读·思考', '思考·交流', '尝试·思考', '随堂练习', '回顾·反思',
    '回顾与思考', '阅读·欣赏', '操作·思考',
    '知识技能', '数学理解', '问题解决', '联系拓广',
    '想一想', '做一做', '议一议', '读一读',
]


def protect_math(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def save(m: re.Match) -> str:
        blocks.append(m.group(0))
        return f'\x00MATH{len(blocks) - 1}\x00'

    text = re.sub(r'\$\$[\s\S]*?\$\$', save, text)
    text = re.sub(r'\$[^$\n]+\$', save, text)
    return text, blocks


def restore_math(text: str, blocks: list[str]) -> str:
    for i, b in enumerate(blocks):
        text = text.replace(f'\x00MATH{i}\x00', b)
    return text


def clean_ocr_spaces(text: str) -> str:
    """中文间空格多为 OCR 断行；标题行不处理。"""
    lines = text.split('\n')
    out = []
    for line in lines:
        if line.startswith('#'):
            out.append(line)
            continue
        prev = None
        while prev != line:
            prev = line
            line = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', line)
        line = re.sub(r'([\u4e00-\u9fff])\s+([，。；：？！、）】》])', r'\1\2', line)
        line = re.sub(r'([（【《])\s+([\u4e00-\u9fff])', r'\1\2', line)
        line = re.sub(r'，\s*，+', '，', line)
        line = re.sub(r'。\s*。+', '。', line)
        line = re.sub(r' {2,}', ' ', line)
        out.append(line)
    return '\n'.join(out)


def ensure_marker_blocks(text: str) -> str:
    """保证模块标记为独立的 **标记** 段。"""
    # 修复误拼：`**阅读·思考无理数的发现**` → 分开
    text = re.sub(
        r'\*\*(阅读·思考)(无理数的发现|勾股世界|漫话勾股)\*\*',
        r'**\1**\n\n**\2**',
        text,
    )
    # 清理旧占位残留
    text = re.sub(
        r'<<<M:\s*\n*\s*\*\*(' + '|'.join(re.escape(m) for m in MARKERS) + r')\*\*\s*\n*\s*>>>',
        r'**\1**',
        text,
    )
    text = re.sub(r'<<<M:\s*>>>', '', text)

    text = re.sub(r'(?:>>?\s*|²>\s*)(数学理解|知识技能|问题解决|联系拓广)\s*—?', r'\1', text)
    text = text.replace('联系拓广一', '联系拓广')
    found: list[str] = []

    def take_bold(m: re.Match) -> str:
        found.append(m.group(1))
        return f'<<<M{len(found) - 1}>>>'

    def take_bare(m: re.Match) -> str:
        found.append(m.group(1))
        return f'<<<M{len(found) - 1}>>>'

    # 先收已有加粗
    text = re.sub(
        r'\*\*(' + '|'.join(re.escape(m) for m in MARKERS) + r')\*\*',
        take_bold,
        text,
    )
    # 再收裸标记（跳过已在占位内）
    text = re.sub(
        r'(?<![<\d])(' + '|'.join(re.escape(m) for m in MARKERS) + r')(?!\*)',
        take_bare,
        text,
    )

    for i, m in enumerate(found):
        text = text.replace(f'<<<M{i}>>>', f'\n\n**{m}**\n\n')

    return text


def ensure_examples(text: str) -> str:
    """例N / 解： 独立成段；不拆开「上面例1中」。"""
    # 清理失败残留 <<<E: ... >>>
    text = re.sub(r'<<<E:\s*\n*\s*\*\*(例\d+)\*\*\s*\n*\s*>>>', r'**\1**', text)
    text = re.sub(r'<<<E:\s*', '', text)
    text = re.sub(r'>>>\s*', '', text)

    text = re.sub(
        r'(上面|在例|见例|在)\s*\n+\s*\*\*(例\d+)\*\*\s*',
        r'\1\2',
        text,
    )
    text = re.sub(r'(上面|在)(例\d+)', r'\1\2', text)

    found: list[str] = []

    def take(m: re.Match) -> str:
        found.append(m.group(1))
        return f'<<<E{len(found) - 1}>>>'

    text = re.sub(r'\*\*(例\d+)\*\*', take, text)
    text = re.sub(
        r'(?<![\u4e00-\u9fffA-Za-z0-9<])(例\d+)(?![\u4e00-\u9fff>\d])',
        take,
        text,
    )
    for i, name in enumerate(found):
        text = text.replace(f'<<<E{i}>>>', f'\n\n**{name}**\n\n')

    text = re.sub(r'\*\*解：\*\*', '<<<SOL>>>', text)
    text = re.sub(r'(?<!\*)解：', '<<<SOL>>>', text)
    text = text.replace('<<<SOL>>>', '\n\n**解：**\n\n')

    return text


def ensure_exercise_headings(text: str) -> str:
    """习题/复习题 → ### 标题（幂等）。"""
    # 先清掉空 ###
    text = re.sub(r'^###\s*$', '', text, flags=re.M)
    # 去掉重复 ### ### 习题
    text = re.sub(r'(###\s*)+习题\s*', '### 习题', text)

    def ex_repl(m: re.Match) -> str:
        return f'\n\n### 习题{m.group(1)}\n\n'

    # 尚未是标题的 习题N.M
    text = re.sub(
        r'(?<!### 习题)(?<!### )习题\s*(\d+\.\d+)',
        ex_repl,
        text,
    )
    text = re.sub(r'###\s*习题\s+(\d+\.\d+)', r'### 习题\1', text)

    text = re.sub(r'(?<!### )复习题(?!\s*\n)', r'\n\n### 复习题\n\n', text)
    text = re.sub(r'###\s*复习题\s*', '### 复习题\n\n', text)

    return text


def break_items(text: str) -> str:
    """大题 1. / 小题 (1) 换行。"""
    text = re.sub(
        r'(\*\*[^*\n]+\*\*)\s*(\d{1,2}\.)\s*',
        r'\1\n\n\2 ',
        text,
    )
    text = re.sub(
        r'([。；：])\s*(\d{1,2}\.)\s*(?=[\u4e00-\u9fff※])',
        r'\1\n\n\2 ',
        text,
    )
    # () 后接下一大题
    text = re.sub(r'(\(\)\s*)(\d{1,2}\.)\s*', r'\1\n\n\2 ', text)
    text = re.sub(
        r'(?<!\\left)\((\d{1,2})\)\s*(?=[\u4e00-\u9fff$※求化简计算判断比较估计填空已知如图])',
        r'\n(\1) ',
        text,
    )
    text = re.sub(r'(?<!\n)\s*(※\d+\.)\s*', r'\n\n\1 ', text)
    return text


def clean_noise(text: str) -> str:
    text = re.sub(r'([。…？！])\s*\d{1,3}\s*(?=\n|$)', r'\1', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff。])(?<!\d)([2345]\d)(\d{1,2}\.)\s*', r'\n\n\2 ', text)
    text = re.sub(r'\s*(\(第\d+题\))\s*', r' \1\n', text)
    text = text.replace('= 2 + i -3=5', '= 2 + 3 = 5')
    text = re.sub(r'\*\*\s*\*\*', '', text)
    # 阅读栏目：短标题单独成行（勿用 ###，避免与节标题混淆）
    text = re.sub(
        r'(\*\*阅读·思考\*\*\n\n)(无理数的发现|勾股世界|漫话勾股)(?=[\u4e00-\u9fff])',
        r'\1**\2**\n\n',
        text,
    )
    text = re.sub(
        r'。(一般地|因此|于是|特别地|实际上|事实上|反过来|假设|从[\u4e00-\u9fff]{0,6}可以看出)',
        r'。\n\n\1',
        text,
    )
    # 中文逗号后误留空格
    text = re.sub(r'，\s+', '，', text)
    return text


def finalize(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(^#{1,3} .+)\n(?!\n|#)', r'\1\n\n', text, flags=re.M)
    # 标题内：第2章实数 → 第2章 实数
    text = re.sub(
        r'^(#+\s*第[一二三四五六七八九十\d]+章)([\u4e00-\u9fff])',
        r'\1 \2',
        text,
        flags=re.M,
    )
    # 节标题粘正文：### 3. 二次根式观察 → 拆开
    text = re.sub(
        r'^(#{2,3}\s+\d+\.\s*[\u4e00-\u9fffA-Za-z0-9（）()?！]{2,16})'
        r'(观察|如图|在一|一般|把一|为了|前面|如果|已知|二次根式也可以)',
        r'\1\n\n\2',
        text,
        flags=re.M,
    )
    lines = [ln.rstrip() for ln in text.split('\n')]
    return '\n'.join(lines).strip() + '\n'


def post_restore_polish(text: str) -> str:
    """公式还原后再断句、补小标题。"""
    # 再防一次误拼
    text = re.sub(
        r'\*\*(阅读·思考)(无理数的发现|勾股世界|漫话勾股)\*\*',
        r'**\1**\n\n**\2**',
        text,
    )
    text = re.sub(
        r'(\*\*阅读·思考\*\*\s*\n+)(无理数的发现)(?=[\u4e00-\u9fff*])',
        r'\1**\2**\n\n',
        text,
    )
    text = re.sub(
        r'(\$[^$\n]+\$)(因此|于是|一般地|特别地)',
        r'\1\n\n\2',
        text,
    )
    text = re.sub(
        r'。\s*(假设边长|从无理数|有理数是能|无理数则是)',
        r'。\n\n\1',
        text,
    )
    text = re.sub(r'。\s+于是', '。\n\n于是', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def reflow(text: str) -> str:
    text, blocks = protect_math(text)
    text = clean_ocr_spaces(text)
    text = ensure_marker_blocks(text)
    text = ensure_examples(text)
    text = ensure_exercise_headings(text)
    text = break_items(text)
    text = clean_noise(text)
    text = finalize(text)
    text = restore_math(text, blocks)
    text = post_restore_polish(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def process_file(path: Path, dry_run: bool = False) -> bool:
    original = path.read_text(encoding='utf-8')
    if original.startswith('---'):
        parts = original.split('---', 2)
        if len(parts) >= 3:
            body = reflow(parts[2].lstrip('\n'))
            new_text = f'---{parts[1]}---\n\n{body}'
        else:
            new_text = reflow(original)
    else:
        new_text = reflow(original)

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
            files.extend(sorted(root.rglob(os.path.join('sections', 'S*.md'))))  # 2026-10-15 架构适配
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
