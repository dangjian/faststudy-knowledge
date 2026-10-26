#!/usr/bin/env python3
"""内容注入管线第 ①② 步的单元测试（book_propose / book_outline / book_apply）。

验收判据取自 spec：**不做「对现存教材 dry-run 逐字节比对」**——现存库是 v1/v2 加大量人工
修正的历史产物，比不上，那是个假闸门。改用小 fixture 走全链路，产出与预期逐字节比对。

运行:
  python test_book_pipeline.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_apply import plan_writes, render_book_index, slice_lines, verify_written  # noqa: E402
from book_outline import dump_outline, load_outline, outline_path, validate_outline  # noqa: E402
from book_propose import scan_headings  # noqa: E402

FIXTURE_MD = """# 天球坐标

天球是一个假想的球面。

## 赤道坐标系

赤经与赤纬构成赤道坐标系。

## 黄道坐标系

黄经与黄纬构成黄道坐标系。

# 恒星视差

视差是测距的基础方法。
"""

BASE_OUTLINE = {
    'textbookId': 'EXT-Astronomy-Basics',
    'contentDir': 'content/七年级/上册/天文/EXT-Astronomy-Basics',
    'meta': {
        'title': '天文学基础',
        'grade': '7',
        'term': '1',
        'subject': 'Astronomy',
        'publisher': '-',
        'origin': 'extension',
        'source': '《天文学新概论》第 4 版',
        'totalPages': 0,
    },
    'sourceMd': ['notes/astronomy.md'],
    'headings': [],
    'chapters': [
        {
            'id': 'C1', 'title': '天球坐标', 'order': 1, 'fromLine': 1, 'toLine': 11,
            'sections': [
                {'id': 'S1', 'title': '赤道坐标系', 'order': 1, 'fromLine': 5, 'toLine': 7},
                {'id': 'S2', 'title': '黄道坐标系', 'order': 2, 'fromLine': 9, 'toLine': 11},
            ],
        },
        {'id': 'C2', 'title': '恒星视差', 'order': 2, 'fromLine': 13, 'toLine': 15, 'sections': []},
    ],
}


def deep(obj):
    return json.loads(json.dumps(obj))


class TestScanHeadings(unittest.TestCase):
    def test_levels_lines_and_chars(self):
        hs = scan_headings(FIXTURE_MD.split('\n'))
        self.assertEqual([(h['level'], h['line'], h['text']) for h in hs], [
            (1, 1, '天球坐标'), (2, 5, '赤道坐标系'), (2, 9, '黄道坐标系'), (1, 13, '恒星视差'),
        ])
        self.assertTrue(all(h['chars'] > 0 for h in hs))

    def test_fenced_code_hash_is_not_a_heading(self):
        md = ['# 真标题', '', '```python', '# 这是注释不是标题', '```', '']
        self.assertEqual([h['text'] for h in scan_headings(md)], ['真标题'])


class TestValidateOutline(unittest.TestCase):
    def test_valid(self):
        validate_outline(deep(BASE_OUTLINE), 'x')

    def test_ext_prefix_origin_interlock(self):
        o = deep(BASE_OUTLINE)
        o['meta']['origin'] = 'textbook'
        o['meta'].pop('source')
        with self.assertRaisesRegex(ValueError, 'EXT-'):
            validate_outline(o, 'x')

    def test_extension_requires_source(self):
        o = deep(BASE_OUTLINE)
        o['meta'].pop('source')
        with self.assertRaisesRegex(ValueError, 'source'):
            validate_outline(o, 'x')

    def test_order_must_be_contiguous_from_one(self):
        o = deep(BASE_OUTLINE)
        o['chapters'][1]['order'] = 3
        with self.assertRaisesRegex(ValueError, 'order'):
            validate_outline(o, 'x')

    def test_chapter_line_spans_must_not_overlap(self):
        o = deep(BASE_OUTLINE)
        o['chapters'][1]['fromLine'] = 10
        with self.assertRaisesRegex(ValueError, '重叠'):
            validate_outline(o, 'x')

    def test_section_span_must_be_inside_chapter(self):
        o = deep(BASE_OUTLINE)
        o['chapters'][0]['sections'][1]['toLine'] = 99
        with self.assertRaisesRegex(ValueError, '超出所属章'):
            validate_outline(o, 'x')

    def test_content_dir_must_end_with_textbook_id(self):
        o = deep(BASE_OUTLINE)
        o['contentDir'] = 'content/七年级/上册/天文'
        with self.assertRaisesRegex(ValueError, 'contentDir'):
            validate_outline(o, 'x')

    def test_bad_chapter_id_shape(self):
        o = deep(BASE_OUTLINE)
        o['chapters'][0]['id'] = 'chapter1'
        with self.assertRaisesRegex(ValueError, 'C<n>'):
            validate_outline(o, 'x')


class TestSliceLines(unittest.TestCase):
    def test_strips_surrounding_blank_lines(self):
        lines = ['', 'a', '', 'b', '', '']
        self.assertEqual(slice_lines(lines, 1, 6), 'a\n\nb')


class TestRenderBookIndex(unittest.TestCase):
    def test_frontmatter_shape(self):
        text = render_book_index(deep(BASE_OUTLINE))
        self.assertTrue(text.startswith('---\ntextbookId: EXT-Astronomy-Basics\n'))
        self.assertIn('origin: extension', text)
        self.assertIn('source: 《天文学新概论》第 4 版', text)
        # 扩展知识无纸质页码：绝不用行号冒充 pageRange（页码语义裁决（2026-08） 裁决）
        self.assertNotIn('pageRange', text)
        self.assertNotIn('fromLine', text)

    def test_repeated_render_is_byte_identical(self):
        a = render_book_index(deep(BASE_OUTLINE))
        b = render_book_index(deep(BASE_OUTLINE))
        self.assertEqual(a, b)


class TestApplyEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'notes').mkdir()
        (self.root / 'notes' / 'astronomy.md').write_text(FIXTURE_MD, encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_full_chain_writes_expected_tree_and_bodies(self):
        outline = deep(BASE_OUTLINE)
        path = outline_path(self.root, outline['textbookId'])
        dump_outline(path, outline)
        loaded = load_outline(path)

        for p, content in plan_writes(self.root, loaded):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        verify_written(self.root, loaded)

        base = self.root / loaded['contentDir']
        got = sorted(str(p.relative_to(base)) for p in base.rglob('*.md'))
        self.assertEqual(got, [
            'chapters/C1/index.md',
            'chapters/C1/sections/S1.md',
            'chapters/C1/sections/S2.md',
            'chapters/C2/index.md',
            'index.md',
        ])

        s1 = (base / 'chapters/C1/sections/S1.md').read_text(encoding='utf-8')
        self.assertEqual(
            s1,
            '---\nsectionId: EXT-Astronomy-Basics-C1-S1\n---\n\n'
            '## 赤道坐标系\n\n赤经与赤纬构成赤道坐标系。\n',
        )
        c2 = (base / 'chapters/C2/index.md').read_text(encoding='utf-8')
        self.assertEqual(
            c2,
            '---\nchapterId: EXT-Astronomy-Basics-C2\ntitle: 恒星视差\n---\n\n'
            '# 恒星视差\n\n视差是测距的基础方法。\n',
        )

    def test_apply_is_idempotent_byte_for_byte(self):
        outline = deep(BASE_OUTLINE)
        dump_outline(outline_path(self.root, outline['textbookId']), outline)
        loaded = load_outline(outline_path(self.root, outline['textbookId']))
        first = {str(p): c for p, c in plan_writes(self.root, loaded)}
        second = {str(p): c for p, c in plan_writes(self.root, loaded)}
        self.assertEqual(first, second)

    def test_verify_written_catches_tampering(self):
        outline = deep(BASE_OUTLINE)
        dump_outline(outline_path(self.root, outline['textbookId']), outline)
        loaded = load_outline(outline_path(self.root, outline['textbookId']))
        for p, content in plan_writes(self.root, loaded):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        idx = self.root / loaded['contentDir'] / 'index.md'
        idx.write_text(idx.read_text(encoding='utf-8').replace('- id: C2', '- id: C9'), encoding='utf-8')
        with self.assertRaises(SystemExit):
            verify_written(self.root, loaded)

    def test_missing_source_md_fails_loud(self):
        outline = deep(BASE_OUTLINE)
        outline['sourceMd'] = ['notes/nope.md']
        dump_outline(outline_path(self.root, outline['textbookId']), outline)
        loaded = load_outline(outline_path(self.root, outline['textbookId']))
        with self.assertRaises(SystemExit):
            plan_writes(self.root, loaded)


if __name__ == '__main__':
    unittest.main(verbosity=2)
