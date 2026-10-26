#!/usr/bin/env python3
"""小学入图谱 P0 单测（primary_common / primary_fix / gen_book_index）。

spec：小学入图管线 §3 P0
运行:
  python3 src/test_primary_onboarding.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gen_book_index import GateError, build_book, main as gen_main, render_index  # noqa: E402
from primary_fix import (  # noqa: E402
    apply_split, check_pages, fix_single_ranges, propose_split, renumber_book, shift_chapter,
)
from primary_common import (  # noqa: E402
    chapter_blocks, find_page, first_heading, load_seed, locate_book, norm, read_doc,
    section_files, set_fm_line,
)

TB = 'PEP-3-1-Test'


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def section_md(sid: str, pr: str, title: str) -> str:
    return f'---\nsectionId: {sid}\npageRange: {pr}\nderivedFrom: x\n---\n\n## {title}\n\n正文。\n'


class Fixture:
    """临时 knowledge 仓 + seed JSON + toc 目录（pipeline_toc.json / ocr_pages）。"""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix='kg-primary-'))
        self.root = self.tmp / 'knowledge'
        self.book = self.root / 'content' / '三年级' / '上册' / '语文' / TB
        self.seed = self.tmp / 'seed.json'
        self.toc_root = self.tmp / 'toc'
        self.chapters: list[dict] = []

    def chapter(self, key: str, title: str, start: int, end: int, sections: list[tuple[str, str]],
                first_no: int = 1, body: str | None = None, is_appendix: bool = False) -> None:
        """sections: [(pageRange 原文, 节标题)]，从 S<first_no> 起编号；body 为章 index.md 正文。"""
        ch_dir = self.book / 'chapters' / key
        write(ch_dir / 'index.md', f'---\nchapterId: {TB}-{key}\ntitle: {title}\n---\n\n'
              + (body if body is not None else f'# {title}\n'))
        for i, (pr, t) in enumerate(sections, first_no):
            write(ch_dir / 'sections' / f'S{i}.md', section_md(f'{TB}-{key}-S{i}', pr, t))
        self.chapters.append({'id': f'{TB}-{key}', 'textbookId': TB, 'title': title,
                              'order': len(self.chapters) + 1, 'startPage': start, 'endPage': end,
                              'isAppendix': is_appendix})

    def save(self, offset: int = 5, total: int = 30, toc_offset: int | None = None) -> None:
        write(self.seed, json.dumps({
            'textbooks': [{'id': TB, 'title': '人教版3年级语文上册', 'grade': '3', 'term': '1', 'subject': '语文',
                           'publisher': 'PEP', 'totalPages': total, 'pageOffset': offset}],
            'chapters': self.chapters,
        }, ensure_ascii=False))
        write(self.toc_root / TB / 'pipeline_toc.json', json.dumps({
            'id': TB, 'offset': offset if toc_offset is None else toc_offset, 'totalPages': total, 'chapters': [],
        }))

    def ocr(self, printed_page: int, text: str, offset: int = 5) -> None:
        write(self.toc_root / TB / 'ocr_pages' / f'{printed_page + offset}.txt', text)

    def sec(self, key: str, n: int) -> Path:
        return self.book / 'chapters' / key / 'sections' / f'S{n}.md'

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp)


class TestCommon(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()

    def tearDown(self) -> None:
        self.f.cleanup()

    def test_load_seed_and_locate(self) -> None:
        self.f.chapter('C2', '第二单元', 11, 20, [('[12, 20]', '3 小鸟')])
        self.f.chapter('C1', '第一单元', 1, 10, [('[2, 10]', '1 秋天')])
        self.f.save()
        books, chapters = load_seed(self.f.seed)
        self.assertEqual(books[TB]['pageOffset'], 5)
        self.assertEqual([c['id'] for c in chapters[TB]], [f'{TB}-C2', f'{TB}-C1'])  # 按 order
        self.assertEqual(locate_book(self.f.root / 'content', TB), self.f.book)
        with self.assertRaises(FileNotFoundError):
            locate_book(self.f.root / 'content', 'PEP-0-0-None')

    def test_section_files_numeric_order(self) -> None:
        self.f.chapter('C1', '第一单元', 1, 30, [(f'[{i}, {i}]', f'第{i}课') for i in range(1, 12)])
        names = [p.name for p in section_files(self.f.book / 'chapters' / 'C1')]
        self.assertEqual(names[8:], ['S9.md', 'S10.md', 'S11.md'])

    def test_set_fm_line_keeps_other_bytes(self) -> None:
        text = section_md('X-C1-S1', '[9]', '标题')
        out = set_fm_line(text, 'pageRange', '[9, 9]')
        self.assertEqual(out, text.replace('pageRange: [9]', 'pageRange: [9, 9]'))
        with self.assertRaises(ValueError):
            set_fm_line(text, 'nope', '1')

    def test_read_doc_and_first_heading(self) -> None:
        self.f.chapter('C1', '第一单元', 1, 10, [('[2, 10]', '1 秋天')])
        fm, body = read_doc(self.f.sec('C1', 1))
        self.assertEqual(fm['pageRange'], [2, 10])
        self.assertEqual(first_heading(body), '1 秋天')
        self.assertIsNone(first_heading('没有标题\n'))

    def test_norm(self) -> None:
        self.assertEqual(norm("Let's go! 第1课 "), 'letsgo第1课')

    def test_find_page_priority_and_bounds(self) -> None:
        pages = {2: norm('Read aloud. apple pie'), 3: norm('Listen and tick.'), 4: ''}
        self.assertEqual(find_page(['Listen and tick.', 'apple pie'], pages, 2, 4), (3, 'heading'))
        self.assertEqual(find_page(['A', 'apple pie'], pages, 2, 4), (2, 'anchor'))  # 标题过短（<4）不参与
        self.assertEqual(find_page(['Listen and tick.'], pages, 4, 4), (None, None))

    def test_chapter_blocks(self) -> None:
        body = ('# Revision X\n\n注：前言。\n\n## Listen\n\n【图：插图】\n\nline one\n\n'
                '## Read\n\n| a | b |\n|---|---|\n\nline two\n')
        blocks = chapter_blocks(body)
        self.assertEqual([b['heading'] for b in blocks], ['Listen', 'Read'])
        self.assertTrue(blocks[0]['text'].startswith('注：前言。\n\n## Listen'))
        self.assertEqual(blocks[0]['anchor'], '注：前言。')
        self.assertEqual(blocks[1]['anchor'], 'line two')
        self.assertNotIn('# Revision X', blocks[0]['text'])

    def test_chapter_blocks_without_h2(self) -> None:
        blocks = chapter_blocks('# Appendix 4 Vocabulary 词汇表\n\n| a | b |\n')
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['heading'], 'Appendix 4 Vocabulary 词汇表')
        self.assertTrue(blocks[0]['text'].startswith('# Appendix 4 Vocabulary'))


class TestSingleRange(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()
        self.f.chapter('C1', '第一单元', 1, 10, [('[2]', '1 秋天'), ('[3, 5]', '2 树叶'), ('[7]', '3 落叶')])
        self.f.save()

    def tearDown(self) -> None:
        self.f.cleanup()

    def test_dry_run_reports_without_writing(self) -> None:
        fixed, manual = fix_single_ranges(self.f.root, self.f.seed, apply=False)
        self.assertEqual(fixed, [f'{TB}-C1-S1'])
        self.assertEqual(len(manual), 1)
        self.assertIn(f'{TB}-C1-S3', manual[0])
        self.assertIn('pageRange: [2]\n', self.f.sec('C1', 1).read_text(encoding='utf-8'))

    def test_apply_only_provable_single_pages(self) -> None:
        fix_single_ranges(self.f.root, self.f.seed, apply=True)
        self.assertIn('pageRange: [2, 2]\n', self.f.sec('C1', 1).read_text(encoding='utf-8'))
        self.assertIn('pageRange: [7]\n', self.f.sec('C1', 3).read_text(encoding='utf-8'))  # 末节 7 ≠ 章末 10，留人工


class TestRenumber(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()
        self.f.chapter('C1', '第一单元', 1, 10, [('[2, 5]', '第1课'), ('[6, 10]', '第2课')])
        self.f.chapter('C2', '第二单元', 11, 20, [('[12, 15]', '第3课'), ('[16, 20]', '第4课')], first_no=3)
        self.f.save()

    def tearDown(self) -> None:
        self.f.cleanup()

    def test_renumber_continuous_chapter(self) -> None:
        moves = renumber_book(self.f.root, TB, apply=True)
        self.assertEqual(moves, [(f'{TB}-C2-S3', f'{TB}-C2-S1'), (f'{TB}-C2-S4', f'{TB}-C2-S2')])
        names = sorted(p.name for p in (self.f.book / 'chapters' / 'C2' / 'sections').iterdir())
        self.assertEqual(names, ['S1.md', 'S2.md'])
        text = self.f.sec('C2', 1).read_text(encoding='utf-8')
        self.assertIn(f'sectionId: {TB}-C2-S1\n', text)
        self.assertIn('## 第3课', text)              # 正文随文件走
        self.assertIn('derivedFrom: x\n', text)      # derivedFrom 不动
        self.assertIn(f'sectionId: {TB}-C1-S1\n', self.f.sec('C1', 1).read_text(encoding='utf-8'))  # C1 不动

    def test_dry_run_writes_nothing(self) -> None:
        renumber_book(self.f.root, TB, apply=False)
        self.assertTrue(self.f.sec('C2', 3).exists())

    def test_gap_refuses(self) -> None:
        self.f.sec('C2', 4).rename(self.f.sec('C2', 5))
        with self.assertRaises(ValueError):
            renumber_book(self.f.root, TB, apply=True)


class TestCheckAndShift(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()
        self.f.chapter('C1', '第一单元', 1, 10, [('[3, 6]', '第1课 我们的好朋友'), ('[7, 11]', '第2课 说话要算数')])
        self.f.save()
        self.f.ocr(2, '第1课 我们的好朋友 ……')
        self.f.ocr(6, '第2课 说话要算数 ……')

    def tearDown(self) -> None:
        self.f.cleanup()

    def test_check_pages_reports_delta(self) -> None:
        lines = check_pages(self.f.root, self.f.seed, self.f.toc_root, [f'{TB}-C1'])
        self.assertIn(f'{TB}-C1-S1\tfm=3\tocr=2\tdelta=1', lines)
        self.assertIn(f'{TB}-C1-S2\tfm=7\tocr=6\tdelta=1', lines)

    def test_shift_chapter(self) -> None:
        shift_chapter(self.f.root, self.f.seed, f'{TB}-C1', -1, apply=True)
        self.assertIn('pageRange: [2, 5]\n', self.f.sec('C1', 1).read_text(encoding='utf-8'))
        self.assertIn('pageRange: [6, 10]\n', self.f.sec('C1', 2).read_text(encoding='utf-8'))


REVISION_BODY = ('# Revision Being a good guest\n\n## Listen and tick.\n\n【图：听录音】\n\n'
                 '## Read aloud.\n\nHello, welcome!\n\n## Look and circle.\n\nWhat colour is it?\n')


class TestSplit(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()
        self.f.chapter('C1', 'Unit 1', 1, 19, [('[2, 19]', 'Part A')])
        self.f.chapter('C7', 'Revision Being a good guest', 20, 23, [], body=REVISION_BODY)
        self.f.chapter('C8', 'Appendix 4 Vocabulary', 24, 25, [], body='# Appendix 4 Vocabulary 词汇表\n\n| a | b |\n',
                       is_appendix=True)
        self.f.save()
        self.f.ocr(20, 'Revision Listen and tick.')
        self.f.ocr(21, 'Read aloud. Hello, welcome! Look and circle.')

    def tearDown(self) -> None:
        self.f.cleanup()

    def test_propose_only_sectionless_chapters(self) -> None:
        prop = propose_split(self.f.root, self.f.seed, self.f.toc_root)
        self.assertEqual([c['chapterId'] for c in prop], [f'{TB}-C7', f'{TB}-C8'])
        self.assertEqual([(b['page'], b['source']) for b in prop[0]['blocks']],
                         [(20, 'heading'), (21, 'heading'), (21, 'heading')])
        self.assertEqual(prop[1]['blocks'], [{'heading': 'Appendix 4 Vocabulary 词汇表', 'page': 24,
                                              'source': 'chapter-start'}])

    def test_apply_groups_by_page(self) -> None:
        prop = propose_split(self.f.root, self.f.seed, self.f.toc_root)
        apply_split(self.f.root, prop, apply=True)
        s1 = self.f.sec('C7', 1).read_text(encoding='utf-8')
        s2 = self.f.sec('C7', 2).read_text(encoding='utf-8')
        self.assertTrue(s1.startswith(f'---\nsectionId: {TB}-C7-S1\npageRange: [20, 20]\n'
                                      f'derivedFrom: content/三年级/上册/语文/{TB}/chapters/C7/index.md\n---\n\n'
                                      '## Listen and tick.\n'))
        self.assertIn('pageRange: [21, 23]', s2)
        self.assertIn('## Read aloud.', s2)
        self.assertIn('## Look and circle.', s2)
        self.assertFalse(self.f.sec('C7', 3).exists())
        self.assertIn('pageRange: [24, 25]', self.f.sec('C8', 1).read_text(encoding='utf-8'))

    def test_apply_refuses_null_page_and_existing_sections(self) -> None:
        prop = propose_split(self.f.root, self.f.seed, self.f.toc_root)
        prop[0]['blocks'][1]['page'] = None
        with self.assertRaises(ValueError):
            apply_split(self.f.root, prop[:1], apply=True)
        prop = propose_split(self.f.root, self.f.seed, self.f.toc_root)
        apply_split(self.f.root, prop, apply=True)
        with self.assertRaises(FileExistsError):
            apply_split(self.f.root, prop, apply=True)


class TestGenBookIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Fixture()
        self.f.chapter('C1', '第一单元 秋天', 1, 10, [('[2, 5]', '1 秋天'), ('[6, 10]', '2 树叶')])
        self.f.chapter('C2', '第二单元', 11, 20, [('[12, 20]', '3 小鸟')], is_appendix=True)

    def tearDown(self) -> None:
        self.f.cleanup()

    def build(self) -> tuple[Path, dict]:
        books, chapters = load_seed(self.f.seed)
        return build_book(self.f.root / 'content', books[TB], chapters[TB], self.f.toc_root)

    def assert_gate(self, code: str) -> None:
        with self.assertRaises(GateError) as cm:
            self.build()
        self.assertTrue(any(p.startswith(code) for p in cm.exception.problems), cm.exception.problems)

    def test_happy_path(self) -> None:
        self.f.save()
        book_dir, fm = self.build()
        self.assertEqual(book_dir, self.f.book)
        self.assertEqual(fm, {
            'textbookId': TB, 'title': '人教版3年级语文上册', 'grade': '3', 'term': '1', 'subject': '语文',
            'publisher': 'PEP', 'totalPages': 30, 'imageOffset': 5, 'origin': 'textbook',
            'outlineSource': 'section-files',
            'chapters': [
                {'id': 'C1', 'title': '第一单元 秋天', 'order': 1, 'pageRange': [1, 10], 'sections': [
                    {'id': 'S1', 'title': '1 秋天', 'order': 1, 'pageRange': [2, 5]},
                    {'id': 'S2', 'title': '2 树叶', 'order': 2, 'pageRange': [6, 10]}]},
                {'id': 'C2', 'title': '第二单元', 'order': 2, 'pageRange': [11, 20], 'sections': [
                    {'id': 'S1', 'title': '3 小鸟', 'order': 1, 'pageRange': [12, 20]}]},
            ],
        })
        text = render_index(fm)
        self.assertTrue(text.startswith(f"---\ntextbookId: {TB}\ntitle: 人教版3年级语文上册\ngrade: '3'\nterm: '1'\n"))
        self.assertTrue(text.endswith('---\n\n# 人教版3年级语文上册\n'))

    def test_g1_offset_mismatch(self) -> None:
        self.f.save(toc_offset=6)
        self.assert_gate('G1')

    def test_g2_single_element(self) -> None:
        self.f.save()
        p = self.f.sec('C1', 1)
        p.write_text(p.read_text(encoding='utf-8').replace('[2, 5]', '[2]'), encoding='utf-8')
        self.assert_gate('G2')

    def test_g3_gap(self) -> None:
        self.f.save()
        self.f.sec('C1', 2).rename(self.f.sec('C1', 3))
        self.assert_gate('G3')

    def test_g4_no_sections(self) -> None:
        self.f.chapter('C3', '第三单元', 21, 30, [])
        self.f.save()
        self.assert_gate('G4')

    def test_g5_outside_chapter(self) -> None:
        self.f.save()
        p = self.f.sec('C2', 1)
        p.write_text(p.read_text(encoding='utf-8').replace('[12, 20]', '[12, 21]'), encoding='utf-8')
        self.assert_gate('G5')

    def test_g7_end_page_beyond_printed(self) -> None:
        self.f.chapters[1]['endPage'] = 28   # totalPages 30 − offset 5 = 25
        self.f.save()
        self.assert_gate('G7')

    def test_g6_dir_mismatch(self) -> None:
        self.f.save()
        write(self.f.book / 'chapters' / 'C9' / 'index.md', '---\nchapterId: x\ntitle: x\n---\n')
        self.assert_gate('G6')

    def test_main_writes_then_refuses_overwrite(self) -> None:
        self.f.save()
        argv = ['--root', str(self.f.root), '--seed', str(self.f.seed), '--toc-root', str(self.f.toc_root)]
        self.assertEqual(gen_main(argv), 0)
        self.assertTrue((self.f.book / 'index.md').is_file())
        self.assertEqual(gen_main(argv), 1)
        self.assertEqual(gen_main(argv + ['--force']), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
