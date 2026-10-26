#!/usr/bin/env python3
"""摄入管线读取层的单元测试（_chapter_num / resolve_pdf_pages / book_frontmatter）。

运行:
  python test_pdf_ocr_to_index.py
  # 或
  python -m unittest test_pdf_ocr_to_index
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_frontmatter import chapters, find_book_dir, image_offset, pdf_pages, read_book  # noqa: E402
from pdf_ocr_to_index import _chapter_num, resolve_pdf_pages  # noqa: E402


class TestChapterNum(unittest.TestCase):
    def test_new_id_format(self):
        self.assertEqual(_chapter_num({'id': 'C1'}), 1)
        self.assertEqual(_chapter_num({'id': 'C14'}), 14)

    def test_legacy_keys(self):
        self.assertEqual(_chapter_num({'chapter': 3}), 3)
        self.assertEqual(_chapter_num({'unit': 'U5'}), 5)
        self.assertEqual(_chapter_num({'unit': 7}), 7)

    def test_exception_ids_return_none(self):
        # 单字符 C（s[1:] 为空）、区间、非数字、缺失 —— 均应容错返回 None，不抛 ValueError
        self.assertIsNone(_chapter_num({'id': 'C'}))
        self.assertIsNone(_chapter_num({'id': 'C1-2'}))
        self.assertIsNone(_chapter_num({'id': '附录'}))
        self.assertIsNone(_chapter_num({'id': None}))


class TestResolvePdfPages(unittest.TestCase):
    """页码语义裁决后（页码语义裁决（2026-08））只剩一条路径：教材页号 + imageOffset。"""

    def test_page_range_plus_offset(self):
        self.assertEqual(resolve_pdf_pages({'pageRange': [11, 13]}, 8), [19, 20, 21])

    def test_zero_offset(self):
        self.assertEqual(resolve_pdf_pages({'pageRange': [1, 3]}, 0), [1, 2, 3])

    def test_missing_page_range_raises(self):
        # imageRange 分支已随裁决撤除：只写 imageRange 的章现在应当报错，而不是被静默接受
        with self.assertRaises(ValueError):
            resolve_pdf_pages({'imageRange': [11, 13]}, 8)
        with self.assertRaises(ValueError):
            resolve_pdf_pages({}, 8)


class TestImageOffset(unittest.TestCase):
    def test_present(self):
        self.assertEqual(image_offset({'textbookId': 'X', 'imageOffset': 5}), 5)

    def test_missing_raises_not_zero(self):
        # imageOffset 缺失处置 的 21 本 imageOffset: null —— 必须抛错而不是当 0 用，
        # 猜错 offset 会让整章 OCR 系统性错页，而错得很像对的
        with self.assertRaises(ValueError):
            image_offset({'textbookId': 'X', 'imageOffset': None})
        with self.assertRaises(ValueError):
            image_offset({'textbookId': 'X'})


class TestReadBookAgainstRealLibrary(unittest.TestCase):
    """只读实测：共用入口能从真实教材的 index.md 取到与 front-matter 一致的章页码。"""

    def test_real_textbook(self):
        content = Path(__file__).resolve().parents[3] / 'content'
        tb_dir = find_book_dir(content, 'PEP-7-1-History')
        book = read_book(tb_dir)
        self.assertEqual(book['textbookId'], 'PEP-7-1-History')
        self.assertEqual(image_offset(book), 5)
        c1 = chapters(book)[0]
        self.assertEqual(c1['id'], 'C1')
        # 教材页 pageRange + imageOffset 5 = 页图编号
        self.assertEqual(pdf_pages(book, c1), [p + 5 for p in range(c1['pageRange'][0], c1['pageRange'][1] + 1)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
