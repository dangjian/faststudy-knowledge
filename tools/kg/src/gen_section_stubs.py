#!/usr/bin/env python3
"""根据书级 index.md front-matter 生成 section 桩文件（分层 v3，见 摄入路径断裂修复）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_frontmatter import chapters, read_book  # noqa: E402


def main() -> int:
    tb_dir = Path(sys.argv[1])
    tb = read_book(tb_dir)
    tid = tb['textbookId']
    for ch in chapters(tb):
        n = str(ch['id']).lstrip('Cc')
        sec_dir = tb_dir / 'chapters' / f'C{n}' / 'sections'
        sec_dir.mkdir(parents=True, exist_ok=True)
        for s in ch.get('sections') or []:
            m = str(s['id']).lstrip('Ss')
            out = sec_dir / f'S{m}.md'
            pr = s.get('pageRange') or []
            pr_yaml = '\n'.join(f'  - {p}' for p in pr)
            content = (
                '---\n'
                f'sectionId: {tid}-C{n}-S{m}\n'
                'pageRange:\n'
                f'{pr_yaml}\n'
                '---\n\n'
                f'# {s["title"]}\n\n'
                '> 待从 index.md 派生。\n'
            )
            out.write_text(content, encoding='utf-8')
            print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
