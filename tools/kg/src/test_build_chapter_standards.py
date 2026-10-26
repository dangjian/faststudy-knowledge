#!/usr/bin/env python3
"""build_chapter_standards.collect_chapters 单测。

回归点（2026-10-01）：脚本曾读已删除的 graph/entities/structure/（v3 去 YAML 化前的旧路径），
collect_chapters 返回空 → 重跑会把 chapter-standards.yaml 写成空列表，初中课标对齐全丢。

运行:
  python3 src/test_build_chapter_standards.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_chapter_standards import collect_chapters  # noqa: E402


def write_book(content: Path, rel: str, tb: str, grade: str, subject: str, chapters: list[tuple[str, str]],
               edition: str | None = '2022版') -> None:
    d = content / rel / tb
    (d / 'chapters').mkdir(parents=True)
    lines = ['---', f'textbookId: {tb}', 'title: 测试', f"grade: '{grade}'", "term: '1'", f'subject: {subject}',
             'publisher: PEP', 'totalPages: 10', 'origin: textbook']
    if edition:
        lines.append(f'standardEdition: {edition}')
    lines.append('chapters:')
    for i, (cid, title) in enumerate(chapters, 1):
        lines += [f'- id: {cid}', f'  title: {title}', f'  order: {i}']
    lines += ['---', '', '# 测试', '']
    (d / 'index.md').write_text('\n'.join(lines), encoding='utf-8')


class TestCollectChapters(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix='kg-chstd-'))
        self.content = self.tmp / 'content'

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_reads_book_index_frontmatter(self) -> None:
        write_book(self.content, '七年级/上册/数学', 'BSDU-7-1-Math', '7', '数学', [('C1', '丰富的图形世界'), ('C2', '有理数')])
        chs = collect_chapters(self.content)
        self.assertEqual([c['chapterId'] for c in chs], ['BSDU-7-1-Math-C1', 'BSDU-7-1-Math-C2'])
        self.assertEqual(chs[0]['subjectEn'], 'Math')
        self.assertEqual(chs[0]['edition'], '2022版')
        self.assertEqual(chs[0]['grade'], '7')

    def test_missing_edition_defaults_2022(self) -> None:
        write_book(self.content, '八年级/上册/历史', 'PEP-8-1-History', '8', '历史', [('C1', '近代')], edition=None)
        self.assertEqual(collect_chapters(self.content)[0]['edition'], '2022版')

    def test_skips_primary_until_p1_6(self) -> None:
        write_book(self.content, '七年级/上册/数学', 'BSDU-7-1-Math', '7', '数学', [('C1', '图形')])
        write_book(self.content, '三年级/上册/数学', 'BSDU-3-1-Math', '3', '数学', [('C1', '混合运算')])
        self.assertEqual([c['textbookId'] for c in collect_chapters(self.content)], ['BSDU-7-1-Math'])

    def test_ignores_chapter_level_index(self) -> None:
        write_book(self.content, '七年级/上册/数学', 'BSDU-7-1-Math', '7', '数学', [('C1', '图形')])
        ch_dir = self.content / '七年级/上册/数学/BSDU-7-1-Math/chapters/C1'
        ch_dir.mkdir(parents=True)
        (ch_dir / 'index.md').write_text('---\nchapterId: BSDU-7-1-Math-C1\ntitle: 图形\n---\n', encoding='utf-8')
        self.assertEqual(len(collect_chapters(self.content)), 1)

    def test_zero_chapters_fails_loud(self) -> None:
        self.content.mkdir()
        with self.assertRaises(SystemExit):
            collect_chapters(self.content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
