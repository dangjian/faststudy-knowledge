#!/usr/bin/env python3
"""reoutline_propose / reoutline_apply 的单元测试（unittest，对齐 test_book_pipeline.py 模式）。"""
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reoutline_propose import compute_id_diff, decide_prose_source, load_snapshot, norm_title, classify_py, normalize_chapter_ids  # noqa: E402
from reoutline_propose import map_concepts, _parse_items_blocks  # noqa: E402
from reoutline_propose import _math_norm, _extract_h2_block_text, _load_concept_data  # noqa: E402
from reoutline_propose import resolve_book_offset  # noqa: E402
from reoutline_ocr import resolve_offset  # noqa: E402

VECTORS = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'contract' / 'section-title-agree.vectors.json'


class TestNormTitle(unittest.TestCase):
    def test_golden_vectors(self):
        v = json.loads(VECTORS.read_text(encoding='utf-8'))
        for c in v['normTitle']:
            self.assertEqual(norm_title(c['input']), c['expected'], msg=c['input'])
        for c in v['classify']:
            self.assertEqual(classify_py(c['pg'], c['kg']), c['expected'], msg=str(c))


class TestDecideProseSource(unittest.TestCase):
    def test_h2_block_unique_and_ocr_and_missing(self):
        md = '# 第一章\n\n导语\n\n## 三角形内角和定理\n\nA\n\n## 三角形内角和定理\n\nB\n'  # 重复 H2 → 多义 → ocr
        h2s = [(5, '三角形内角和定理'), (9, '三角形内角和定理')]
        self.assertEqual(decide_prose_source('三角形内角和定理', h2s, [8, 12], {}), 'ocr')  # 多义
        h2s_unique = [(5, '三角形内角和定理')]
        self.assertEqual(decide_prose_source('三角形内角和定理', h2s_unique, [8, 12], {}), 'h2_block')
        self.assertEqual(decide_prose_source('新节', h2s_unique, None, {}), 'missing')  # 无页码无 metadata
        self.assertEqual(decide_prose_source('新节', h2s_unique, None, {'新节': [10, 12]}), 'ocr')  # metadata 兜底


class TestIdDiff(unittest.TestCase):
    def test_kept_replaced_added_dropped(self):
        old = {'A-C1-S1': '第1单元 第一章', 'A-C1-S2': '旧节二', 'A-C2-S1': '旧章二节'}
        new = {'A-C1-S1': '第一章', 'A-C1-S2': '第二章', 'A-C1-S3': '全新节'}
        d = compute_id_diff(old, new)
        self.assertEqual(d['kept'], [])
        self.assertEqual(d['replaced'], ['A-C1-S1', 'A-C1-S2'])
        self.assertEqual(d['added'], ['A-C1-S3'])
        self.assertEqual(d['dropped'], ['A-C2-S1'])


class TestApply(unittest.TestCase):
    def _make_fixture(self, tmp: Path):
        book = tmp / 'content' / 'B'
        (book / 'chapters' / 'C1').mkdir(parents=True)
        (book / 'chapters' / 'C1' / 'index.md').write_text(
            '---\nchapterId: B-C1\ntitle: 第一章\n---\n\n# 第一章\n\n导语段。\n\n## 旧节\n\n旧内容。\n', encoding='utf-8')
        (book / 'items').mkdir()
        # 2026-09-27 刷题层移除：items md 不再含 ## 习题 段（空壳文件合法）
        (book / 'items' / 'C1-S1.md').write_text(
            '---\nsectionId: B-C1-S1\n---\n', encoding='utf-8')
        (tmp / 'tools/kg/state/ingest/B/prose').mkdir(parents=True)
        (tmp / 'tools/kg/state/ingest/B/prose/C1-S1.md').write_text('新节一正文 习题甲。', encoding='utf-8')
        (tmp / 'tools/kg/state/ingest/B/prose/C1-S2.md').write_text('新节二正文。', encoding='utf-8')
        (tmp / 'graph' / 'relations').mkdir(parents=True)
        (tmp / 'graph' / 'relations' / 'covered_by.yaml').write_text(
            '- from: concept:数学:甲\n  to: B-C1-S1\n', encoding='utf-8')
        ledger = {
            'textbookId': 'B', 'contentDir': 'content/B', 'confirmed': True,
            'chapters': [{
                'chapterId': 'B-C1', 'dir': 'chapters/C1', 'pgTitle': '第一章', 'order': 1,
                'pageRange': [1, 10], 'imageOffset': 0,
                'sections': [
                    {'id': 'B-C1-S1', 'sId': 'S1', 'title': '新节一', 'order': 1, 'pageRange': [1, 5], 'proseSource': 'ocr'},
                    {'id': 'B-C1-S2', 'sId': 'S2', 'title': '新节二', 'order': 2, 'pageRange': [6, 10], 'proseSource': 'ocr'},
                ],
            }],
            'idDiff': {'kept': [], 'replaced': ['B-C1-S1'], 'added': ['B-C1-S2'], 'dropped': []},
            'conceptRemap': {'mapped': {}, 'unmapped': []}, 'unmappedConcepts': [],
        }
        return ledger

    def test_apply_idempotent_and_content(self):
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            importlib.reload(reoutline_apply)
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            ch = (tmp / 'content/B/chapters/C1/index.md').read_text(encoding='utf-8')
            self.assertIn('## 新节一', ch)  # 新 H2 并入
            self.assertIn('## 新节二', ch)
            self.assertIn('导语段', ch)  # 导语保留
            self.assertNotIn('## 旧节', ch)  # 旧 H2 被目标态替换
            s2 = (tmp / 'content/B/chapters/C1/sections/S2.md').read_text(encoding='utf-8')
            self.assertIn('# 新节二', s2)
            self.assertIn('pageRange: [6, 10]', s2)
            snap = (tmp / 'content/B/chapters/C1/index.md').read_text(encoding='utf-8')
            # 幂等：再跑一遍逐字节不变
            before = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            after = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_section_prose_uses_chapter_prefixed_filename(self):
        """prose 文件以 <章短id>-<sId>.md 命名（如 C1-S2.md），
        apply 后节 md 与章 index 均含对应 prose 正文内容。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            importlib.reload(reoutline_apply)
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)

            # 节 md 正文含 prose 特征子串
            s1 = (tmp / 'content/B/chapters/C1/sections/S1.md').read_text(encoding='utf-8')
            self.assertIn('新节一正文', s1)
            self.assertIn('习题甲。', s1)
            s2 = (tmp / 'content/B/chapters/C1/sections/S2.md').read_text(encoding='utf-8')
            self.assertIn('新节二正文', s2)

            # 章 index 中对应 H2 下也含 prose
            ch = (tmp / 'content/B/chapters/C1/index.md').read_text(encoding='utf-8')
            idx_h2 = ch.index('## 新节一')
            idx_next_h2 = ch.index('## 新节二')
            s1_block = ch[idx_h2:idx_next_h2]
            self.assertIn('新节一正文', s1_block)
            self.assertIn('习题甲。', s1_block)

    def test_yaml_anchor_replace_regex_guard(self):
        """re.escape(old)+(?!\\d) 防 E1 吃 E11。"""
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = '- from: exercise:B-E1\n  to: concept:数学:甲\n- from: exercise:B-E11\n  to: concept:数学:乙\n'
        result = reoutline_apply.replace_id_strict(text, 'exercise:B-E1', 'exercise:B-NEW-E1')
        self.assertIn('exercise:B-NEW-E1', result)
        self.assertIn('exercise:B-E11', result)  # E11 不应被误伤
        self.assertEqual(result.count('exercise:B-'), 2)  # 总共两个实体

    def test_unconfirmed_ledger_exits(self):
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            ledger['confirmed'] = False
            importlib.reload(reoutline_apply)
            with self.assertRaises(SystemExit):
                reoutline_apply.apply_ledger(tmp, ledger, apply=True)

    def test_book_fm_rewrite_and_verify(self):
        """书级 index.md front-matter 重写 + verify_written 集成测试。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            # 加书级 index.md
            book_md = (
                '---\n'
                'textbookId: B\n'
                'title: B 教材\n'
                'grade: \'7\'\n'
                'subject: 数学\n'
                'chapters:\n'
                '- id: C1\n'
                '  title: 第一章 旧标题\n'
                '  order: 1\n'
                '  pageRange:\n'
                '  - 1\n'
                '  - 8\n'
                '  sections:\n'
                '  - id: S1\n'
                '    title: 旧节\n'
                '    order: 1\n'
                '---\n'
                '\n'
                '# B 教材\n'
                '\n'
                '前言。\n'
            )
            (tmp / 'content' / 'B' / 'index.md').write_text(book_md, encoding='utf-8')

            importlib.reload(reoutline_apply)
            skipped = reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            self.assertEqual(skipped, [])

            # 回读验证
            from book_frontmatter import parse_frontmatter
            text = (tmp / 'content/B/index.md').read_text(encoding='utf-8')
            fm = parse_frontmatter(text, 'test')

            # outlineSource 新增
            self.assertEqual(fm['outlineSource'], 'catalog-toc')
            # title 保留
            self.assertEqual(fm['title'], 'B 教材')
            # grade/subject 保留
            self.assertEqual(fm['grade'], '7')
            self.assertEqual(fm['subject'], '数学')
            # 章 title 保留原值（不被 pgTitle 覆盖）
            self.assertEqual(fm['chapters'][0]['title'], '第一章 旧标题')
            # 章 pageRange/order 用 PG 值
            self.assertEqual(fm['chapters'][0]['pageRange'], [1, 10])
            self.assertEqual(fm['chapters'][0]['order'], 1)
            # 节全量重写为 PG 值
            secs = fm['chapters'][0]['sections']
            self.assertEqual(len(secs), 2)
            self.assertEqual(secs[0]['id'], 'S1')
            self.assertEqual(secs[0]['title'], '新节一')
            self.assertEqual(secs[0]['pageRange'], [1, 5])
            self.assertEqual(secs[1]['id'], 'S2')
            self.assertEqual(secs[1]['title'], '新节二')
            self.assertEqual(secs[1]['pageRange'], [6, 10])
            # 前言保留
            self.assertIn('前言。', text)

            # 幂等
            before = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            after = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_apply_covered_by_concept_to_override(self):
        """conceptSectionMap 中概念 → to 改写为新节 id；
        unmapped 概念 → 块删除；两概念共存一条 yaml 时互不干扰。"""
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = (
            '# header\n'
            '- from: concept:数学:甲\n'
            '  to: OLD-C1-S1\n'
            '- from: concept:数学:乙\n'
            '  to: OLD-C1-S2\n'
            '- from: concept:数学:丙\n'
            '  to: OLD-C1-S1\n'
            '- from: concept:数学:无关\n'
            '  to: OTHER-C1-S1\n'
        )
        section_pairs = [('OLD-C1-S1', 'NEW-C1-S1'), ('OLD-C1-S2', 'NEW-C1-S2')]
        concept_remap = {'mapped': {}, 'unmapped': []}
        unmapped_concepts = ['concept:数学:乙']  # 乙未映射 → 删除
        concept_to = {
            'concept:数学:甲': 'NEW-C1-S3',  # 甲被概念感知重写到 C1-S3
            # 丙：不在 concept_to，也不在 unmapped → 走普通节 id 替换 OLD→NEW
        }
        affected = {'OLD-C1-S1', 'OLD-C1-S2'}
        result, deleted = reoutline_apply.apply_covered_by_remap(
            text, section_pairs, concept_remap, unmapped_concepts,
            affected_section_ids=affected, concept_to=concept_to,
        )
        # 甲 → to 改写为 NEW-C1-S3（概念感知优先）
        self.assertIn('concept:数学:甲', result)
        self.assertIn('NEW-C1-S3', result)
        # 乙 → 删除
        self.assertNotIn('concept:数学:乙', result)
        self.assertEqual(deleted, 1)
        # 丙 → 普通节 id 替换 OLD→NEW
        self.assertIn('concept:数学:丙', result)
        self.assertIn('NEW-C1-S1', result)
        # 无关保留
        self.assertIn('concept:数学:无关', result)
        self.assertIn('OTHER-C1-S1', result)
        # header 保留
        self.assertIn('# header', result)

    def test_apply_concepts_source_ref_per_concept(self):
        """两个概念分别映射不同新节 → sourceRef 各自改写正确；
        unmapped 概念 sourceRef 不变。"""
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = (
            '- id: concept:数学:甲\n'
            '  type: Concept\n'
            '  sourceRef: content/OLD/chapters/C1/sections/S1.md\n'
            '  explanation: 甲解释\n'
            '- id: concept:数学:乙\n'
            '  type: Concept\n'
            '  sourceRef: content/OLD/chapters/C1/sections/S2.md\n'
            '  explanation: 乙解释\n'
            '- id: concept:数学:丙\n'
            '  type: Concept\n'
            '  sourceRef: content/OTHER/chapters/C1/sections/S1.md\n'
            '  explanation: 丙解释\n'
        )
        old_to_new = {}  # 全局路径替换为空，验证 concept_ref 独立生效
        concept_ref = {
            'concept:数学:甲': 'content/NEW/chapters/C1/sections/S3.md',
            'concept:数学:乙': 'content/NEW/chapters/C2/sections/S1.md',
            # 丙不在 concept_ref 中 → sourceRef 不变
        }
        result = reoutline_apply.apply_concepts_source_remap(text, old_to_new, concept_ref=concept_ref)
        # 甲 → 新路径
        self.assertIn('sourceRef: content/NEW/chapters/C1/sections/S3.md', result)
        # 乙 → 新路径
        self.assertIn('sourceRef: content/NEW/chapters/C2/sections/S1.md', result)
        # 丙 → 原路径不变
        self.assertIn('sourceRef: content/OTHER/chapters/C1/sections/S1.md', result)
        # 原路径不应再出现（甲和乙的）
        self.assertNotIn('content/OLD/chapters/C1/sections/S1.md', result)
        self.assertNotIn('content/OLD/chapters/C1/sections/S2.md', result)
        # explanation 不变
        self.assertIn('甲解释', result)
        self.assertIn('乙解释', result)
        self.assertIn('丙解释', result)

    def test_illustration_carry_idempotent_multi_blocks(self):
        """插图表搬运二次执行逐字节幂等：多来源插图表并入目标节(S1)后，
        再跑一次 apply 不得丢失第 2..N 个插图区块（7-2-Math 二次 apply 暴露）。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            book = tmp / 'content' / 'B'
            # 旧 items：C1-S1 仅插图块A；C1-S2 仅插图块B；C1-S3 仅插图块C（无新节对应，将被删）
            # 2026-09-27 刷题层移除：items md 不再有 E 块，插图区块为唯一可搬运内容
            (book / 'items' / 'C1-S1.md').write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 插图\n\n'
                '| id | type | ref | 说明 |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S1:图A | illustration |  | 插图A |\n', encoding='utf-8')
            (book / 'items' / 'C1-S2.md').write_text(
                '---\nsectionId: B-C1-S2\n---\n\n## 插图\n\n'
                '| id | type | ref | 说明 |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S2:图B | illustration |  | 插图B |\n', encoding='utf-8')
            (book / 'items' / 'C1-S3.md').write_text(
                '---\nsectionId: B-C1-S3\n---\n\n## 插图\n\n'
                '| id | type | ref | 说明 |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S3:图C | illustration |  | 插图C |\n', encoding='utf-8')
            # 台账：全部插图搬运至 C1-S1
            ledger['figCarryover'] = [{'chapter': 'C1', 'carryToSection': 'C1-S1', 'figCount': 3}]

            importlib.reload(reoutline_apply)
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            s1_first = (book / 'items' / 'C1-S1.md').read_text(encoding='utf-8')
            self.assertIn('图A', s1_first)
            self.assertIn('图B', s1_first)
            self.assertIn('图C', s1_first)  # 三个插图表全部并入 S1
            self.assertFalse((book / 'items' / 'C1-S3.md').exists())  # 旧桶删除

            # 二次执行：逐字节幂等（插图区块一个都不能少）
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            s1_second = (book / 'items' / 'C1-S1.md').read_text(encoding='utf-8')
            self.assertEqual(s1_first, s1_second)

    def test_covered_by_dropped_section_edges_deleted(self):
        """idDiff.dropped 的旧节也属受影响面：unmapped 概念指向 dropped 节的边整块删除，
        防止 to 悬空（apply 后 lint referential-integrity error 级，7-2-Math 首例暴露）。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            ledger['idDiff']['dropped'] = ['B-C0-S9']
            ledger['conceptRemap']['unmapped'] = ['concept:数学:丙']
            cb = tmp / 'graph' / 'relations' / 'covered_by.yaml'
            cb.write_text(
                '- from: concept:数学:甲\n'
                '  to: B-C1-S1\n'
                '- from: concept:数学:丙\n'
                '  to: B-C0-S9\n',
                encoding='utf-8')
            importlib.reload(reoutline_apply)
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            out = cb.read_text(encoding='utf-8')
            self.assertIn('B-C1-S1', out)  # 正常边保留
            self.assertNotIn('B-C0-S9', out)  # dropped 节的 unmapped 边整块删除
            self.assertNotIn('concept:数学:丙', out)

    def test_dry_run_does_not_write(self):
        """apply=False 时不落盘，文件内容保持原状。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            importlib.reload(reoutline_apply)

            before = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}
            skipped = reoutline_apply.apply_ledger(tmp, ledger, apply=False)
            after = {str(p.relative_to(tmp)): p.read_bytes() for p in tmp.rglob('*') if p.is_file()}

            self.assertEqual(before, after)  # 不落盘
            self.assertEqual(skipped, [])  # 刷题层移除后无闸门，跳过恒为空

    def test_items_illustration_table_carried_verbatim(self):
        """插图区块逐字节搬运到目标新节（C1-S1）；items md 不再含 ## 习题 段。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            book = tmp / 'content' / 'B'
            fig_table = (
                '## 插图\n\n'
                '| id | figType | render | description |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S1:图1 | illustration |  | 图1 |\n'
                '| fig:B:B-C1-S1:图2 | illustration |  | 图2 |\n'
            )
            (book / 'items' / 'C1-S1.md').write_text(
                '---\nsectionId: B-C1-S1\n---\n\n' + fig_table, encoding='utf-8')
            ledger['figCarryover'] = [{'chapter': 'C1', 'carryToSection': 'C1-S1', 'figCount': 2}]

            importlib.reload(reoutline_apply)
            skipped = reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            self.assertEqual(skipped, [])
            new_items = (book / 'items' / 'C1-S1.md').read_text(encoding='utf-8')
            self.assertIn(fig_table, new_items)  # 插图区块逐字节保留
            self.assertNotIn('## 习题', new_items)  # 刷题层不回流

    def test_items_illustration_table_idempotent(self):
        """插图搬运二次执行逐字节幂等（多来源表并入后不丢失、不重复）。"""
        import importlib, reoutline_apply
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ledger = self._make_fixture(tmp)
            book = tmp / 'content' / 'B'
            (book / 'items' / 'C1-S1.md').write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 插图\n\n'
                '| id | figType | render | description |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S1:图1 | illustration |  | 图1 |\n', encoding='utf-8')
            ledger['figCarryover'] = [{'chapter': 'C1', 'carryToSection': 'C1-S1', 'figCount': 1}]

            importlib.reload(reoutline_apply)
            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            after1 = (book / 'items' / 'C1-S1.md').read_text(encoding='utf-8')
            self.assertEqual(after1.count('## 插图'), 1)
            self.assertNotIn('## 习题', after1)

            reoutline_apply.apply_ledger(tmp, ledger, apply=True)
            after2 = (book / 'items' / 'C1-S1.md').read_text(encoding='utf-8')
            self.assertEqual(after1, after2)  # 逐字节幂等
            self.assertEqual(after2.count('## 插图'), 1)

    def test_verify_written_partial_skip(self):
        """验证部分章跳过时的 verify_written 逻辑：
        1. 书级 front-matter 应包含全部章（包括跳过章）
        2. 跳过章只保留旧节列表（无需校验节数/标题）
        3. 非跳过章严格校验节数、id、标题
        """
        import importlib, reoutline_apply
        from book_frontmatter import parse_frontmatter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            # 创建包含2章的fixture
            book_dir = tmp / 'content' / 'B'
            book_dir.mkdir(parents=True)
            (book_dir / 'chapters' / 'C1').mkdir(parents=True)
            (book_dir / 'chapters' / 'C2').mkdir(parents=True)

            # 书级index.md：包含2章，C2是跳过章（保留旧S1）
            book_md = (
                '---\n'
                'textbookId: B\n'
                'title: B 教材\n'
                'chapters:\n'
                '- id: C1\n'
                '  title: 第一章\n'
                '  order: 1\n'
                '  sections:\n'
                '  - id: S1\n'
                '    title: 新节一\n'
                '    order: 1\n'
                '  - id: S2\n'
                '    title: 新节二\n'
                '    order: 2\n'
                '- id: C2\n'
                '  title: 第二章\n'
                '  order: 2\n'
                '  sections:\n'
                '  - id: S1\n'
                '    title: 旧节一\n'
                '    order: 1\n'
                '---\n'
                '\n'
                '# B 教材\n'
                '\n'
                '前言。\n'
            )
            (book_dir / 'index.md').write_text(book_md, encoding='utf-8')

            # 章级文件
            (book_dir / 'chapters' / 'C1' / 'index.md').write_text(
                '---\nchapterId: B-C1\ntitle: 第一章\n---\n\n# 第一章\n\n导语\n\n## 新节一\n\n内容\n\n## 新节二\n\n内容\n', encoding='utf-8'
            )
            (book_dir / 'chapters' / 'C2' / 'index.md').write_text(
                '---\nchapterId: B-C2\ntitle: 第二章\n---\n\n# 第二章\n\n导语\n\n## 旧节一\n\n内容\n', encoding='utf-8'
            )

            # 构造台账：2章，C2被跳过
            ledger = {
                'textbookId': 'B', 'contentDir': 'content/B', 'confirmed': True,
                'chapters': [
                    {
                        'chapterId': 'B-C1', 'dir': 'chapters/C1', 'pgTitle': '第一章', 'order': 1,
                        'sections': [
                            {'id': 'B-C1-S1', 'sId': 'S1', 'title': '新节一', 'order': 1},
                            {'id': 'B-C1-S2', 'sId': 'S2', 'title': '新节二', 'order': 2},
                        ],
                    },
                    {
                        'chapterId': 'B-C2', 'dir': 'chapters/C2', 'pgTitle': '第二章', 'order': 2,
                        'sections': [
                            {'id': 'B-C2-S1', 'sId': 'S1', 'title': '旧节一', 'order': 1},
                        ],
                    }
                ],
                'idDiff': {'kept': [], 'replaced': [], 'added': [], 'dropped': []},
                'itemsRemap': {}, 'conceptRemap': {'mapped': {}, 'unmapped': []}, 'unmappedConcepts': [],
            }

            importlib.reload(reoutline_apply)
            # 正常情况：包含全部章，C2被跳过，应该通过
            skipped = {'B-C2'}
            reoutline_apply.verify_written(tmp, ledger, skipped)

            # 异常情况：书级front-matter丢掉了被跳过的章C2，应该报错
            bad_book_md = (
                '---\n'
                'textbookId: B\n'
                'title: B 教材\n'
                'chapters:\n'
                '- id: C1\n'
                '  title: 第一章\n'
                '  order: 1\n'
                '  sections:\n'
                '  - id: S1\n'
                '    title: 新节一\n'
                '    order: 1\n'
                '  - id: S2\n'
                '    title: 新节二\n'
                '    order: 2\n'
                '---\n'
                '\n'
                '# B 教材\n'
                '\n'
                '前言。\n'
            )
            (book_dir / 'index.md').write_text(bad_book_md, encoding='utf-8')

            with self.assertRaises(SystemExit):
                reoutline_apply.verify_written(tmp, ledger, skipped)

    def test_apply_covered_by_unmapped_concepts_dict_format(self):
        """测试 unmappedConcepts 为 dict 列表（含 conceptId/reason/evidenceTried）的兼容情况。"""
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = (
            '# header\n'
            '- from: concept:数学:甲\n'
            '  to: OLD-C1-S1\n'
            '- from: concept:数学:乙\n'
            '  to: OLD-C1-S2\n'
            '- from: concept:数学:丙\n'
            '  to: OLD-C1-S1\n'
        )
        section_pairs = [('OLD-C1-S1', 'NEW-C1-S1'), ('OLD-C1-S2', 'NEW-C1-S2')]
        concept_remap = {'mapped': {}, 'unmapped': []}
        # 测试 dict 格式的 unmappedConcepts
        unmapped_concepts = [
            {'conceptId': 'concept:数学:乙', 'reason': 'multiMatch', 'evidenceTried': []},
            {'conceptId': 'concept:数学:丙', 'reason': 'zeroMatch', 'evidenceTried': []}
        ]
        affected = {'OLD-C1-S1', 'OLD-C1-S2'}
        result, deleted = reoutline_apply.apply_covered_by_remap(
            text, section_pairs, concept_remap, unmapped_concepts,
            affected_section_ids=affected,
        )
        # 乙和丙都应该被删除
        self.assertNotIn('concept:数学:乙', result)
        self.assertNotIn('concept:数学:丙', result)
        self.assertEqual(deleted, 2)
        # 甲保留
        self.assertIn('concept:数学:甲', result)

    def test_apply_covered_by_unmapped_concepts_string_format(self):
        """测试 unmappedConcepts 为字符串列表的兼容情况（向后兼容）。"""
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = (
            '# header\n'
            '- from: concept:数学:甲\n'
            '  to: OLD-C1-S1\n'
            '- from: concept:数学:乙\n'
            '  to: OLD-C1-S2\n'
            '- from: concept:数学:丙\n'
            '  to: OLD-C1-S1\n'
        )
        section_pairs = [('OLD-C1-S1', 'NEW-C1-S1'), ('OLD-C1-S2', 'NEW-C1-S2')]
        concept_remap = {'mapped': {}, 'unmapped': []}
        # 测试字符串格式的 unmappedConcepts
        unmapped_concepts = ['concept:数学:乙', 'concept:数学:丙']
        affected = {'OLD-C1-S1', 'OLD-C1-S2'}
        result, deleted = reoutline_apply.apply_covered_by_remap(
            text, section_pairs, concept_remap, unmapped_concepts,
            affected_section_ids=affected,
        )
        # 乙和丙都应该被删除
        self.assertNotIn('concept:数学:乙', result)
        self.assertNotIn('concept:数学:丙', result)
        self.assertEqual(deleted, 2)
        # 甲保留
        self.assertIn('concept:数学:甲', result)


class TestMapConcepts(unittest.TestCase):
    def test_unique_maps_multi_zero_unmapped(self):
        # C1-S1 含 "一元一次不等式" 和 "定理"；C1-S2 含 "定理"
        prose = {
            'C1-S1': '一元一次不等式的定理：左右两边都是整式',
            'C1-S2': '三角形内角和定理等于180度',
        }
        edges = [
            {'conceptId': 'concept:数学:一元一次不等式', 'title': '一元一次不等式', 'to': 'B-C1-S1'},  # 仅 C1-S1 → mapped
            {'conceptId': 'concept:数学:公共概念', 'title': '定理', 'to': 'B-C1-S1'},  # 两节都含 → multiMatch
            {'conceptId': 'concept:数学:不存在', 'title': '分贝', 'to': 'B-C1-S1'},  # 两节都不含 → zeroMatch
        ]
        r = map_concepts(edges, prose)
        self.assertEqual(r['mapped']['concept:数学:一元一次不等式']['section'], 'C1-S1')
        self.assertEqual(r['mapped']['concept:数学:一元一次不等式']['evidence'], 'title')
        self.assertEqual(r['unmapped'][0]['reason'], 'multiMatch')
        self.assertEqual(r['unmapped'][1]['reason'], 'zeroMatch')

    def test_concept_evidence_chain_alias_explanation(self):
        """title 零命中、alias 唯一命中 → evidence='alias'；
        title 多命中、explanation 唯一 → evidence='explanation'。"""
        prose = {
            'C1-S1': '勾股定理又称毕达哥拉斯定理，直角三角形两直角边的平方和等于斜边的平方。',
            'C1-S2': '勾股定理的逆定理：如果三角形两条边的平方和等于第三边的平方，那么这个三角形是直角三角形。',
            'C1-S3': '本节介绍完全平方公式，两数和的平方等于它们的平方和加积的二倍。',
        }
        edges = [
            # alias 唯一命中（title "毕达哥拉斯" 在 prose 中没有，但 alias "毕达哥拉斯定理" 仅 C1-S1 有）
            {'conceptId': 'concept:数学:勾股定理', 'title': '勾股定理', 'to': 'B-C1-S1'},
            # title 多命中（勾股定理在两节），但 explanation 子句唯一命中 C1-S2
            {'conceptId': '概念:数学:勾股逆定理', 'title': '勾股逆定理', 'to': 'B-C1-S2'},
        ]
        concept_data = {
            'concept:数学:勾股定理': {
                'title': '勾股定理',
                'aliases': ['毕达哥拉斯定理', '商高定理'],
                'explanation': '直角三角形的重要定理。',
            },
            '概念:数学:勾股逆定理': {
                'title': '勾股逆定理',
                'aliases': [],
                'explanation': '如果三角形两条边的平方和等于第三边的平方，那么这个三角形是直角三角形。这是勾股定理的逆用。',
            },
        }
        r = map_concepts(edges, prose, concept_data=concept_data)
        # 勾股定理：title 双命中（C1-S1、C1-S2 都含"勾股定理"），alias "毕达哥拉斯定理" 仅 C1-S1 → alias 级唯一
        self.assertEqual(r['mapped']['concept:数学:勾股定理']['section'], 'C1-S1')
        self.assertEqual(r['mapped']['concept:数学:勾股定理']['evidence'], 'alias')
        # 勾股逆定理：title 零命中？不，"勾股逆定理" 出现在 C1-S2 开头吗？看 prose C1-S2 是 "勾股定理的逆定理"
        # title "勾股逆定理" 归一后 = "勾股逆定理"，prose 中无精确匹配 → 0 命中
        # explanation 中的长句 "如果三角形两条边的平方和等于第三边的平方，那么这个三角形是直角三角形" 仅 C1-S2 有
        self.assertEqual(r['mapped']['概念:数学:勾股逆定理']['section'], 'C1-S2')
        self.assertEqual(r['mapped']['概念:数学:勾股逆定理']['evidence'], 'explanation')

    def test_concept_evidence_fig_route(self):
        """title/alias/explanation 全空、fig 唯一定位 → evidence='fig'；
        两 fig 定位不同节 → multiMatch。"""
        prose = {
            'C1-S1': '【图：图1-1，三角形示意图】正文内容。',
            'C1-S2': '【图：图1-2，直角三角形】另一节内容。',
            'C1-S3': '【图：图1-3，钝角三角形】第三节内容。',
        }
        edges = [
            {'conceptId': 'concept:数学:三角形', 'title': '', 'to': 'B-C1-S1'},
            {'conceptId': 'concept:数学:多图概念', 'title': '', 'to': 'B-C1-S1'},
        ]
        concept_data = {
            'concept:数学:三角形': {'title': '', 'aliases': [], 'explanation': ''},
            'concept:数学:多图概念': {'title': '', 'aliases': [], 'explanation': ''},
        }
        fig_map = {
            'concept:数学:三角形': ['fig:B:B-C1-S1:图1-1'],  # 仅 C1-S1 → fig 级唯一
            'concept:数学:多图概念': ['fig:B:B-C1-S1:图1-1', 'fig:B:B-C1-S2:图1-2'],  # 两节 → multi
        }
        r = map_concepts(edges, prose, concept_data=concept_data, fig_map=fig_map)
        self.assertEqual(r['mapped']['concept:数学:三角形']['section'], 'C1-S1')
        self.assertEqual(r['mapped']['concept:数学:三角形']['evidence'], 'fig')
        # 多图概念：fig 级两命中 → unmapped multiMatch
        unmapped_ids = [u['conceptId'] for u in r['unmapped']]
        self.assertIn('concept:数学:多图概念', unmapped_ids)
        idx = unmapped_ids.index('concept:数学:多图概念')
        self.assertEqual(r['unmapped'][idx]['reason'], 'multiMatch')

    def test_concept_unmapped_records_evidence_tried(self):
        """全级无唯一 → unmapped 且 evidenceTried 存在。"""
        prose = {
            'C1-S1': '内容A',
            'C1-S2': '内容B',
        }
        edges = [
            {'conceptId': 'concept:数学:不存在的概念', 'title': '完全不存在', 'to': 'B-C1-S1'},
        ]
        concept_data = {
            'concept:数学:不存在的概念': {
                'title': '完全不存在',
                'aliases': ['也不存在'],
                'explanation': '短。',  # < 8 字会被跳过
            },
        }
        fig_map = {'concept:数学:不存在的概念': ['fig:B:x:图不存在']}
        r = map_concepts(edges, prose, concept_data=concept_data, fig_map=fig_map)
        self.assertEqual(len(r['unmapped']), 1)
        u = r['unmapped'][0]
        self.assertIn('evidenceTried', u)
        levels = [e['level'] for e in u['evidenceTried']]
        self.assertEqual(levels, ['title', 'alias', 'explanation', 'fig'])
        for e in u['evidenceTried']:
            self.assertIn('hits', e)
            self.assertIsInstance(e['hits'], int)


class TestParseItemsBlocks(unittest.TestCase):
    """_parse_items_blocks：刷题层移除后仅做 H2 白名单校验与 fig 计数。"""

    def test_exercise_section_raises(self):
        """## 习题 段 = 历史文件回流 → SystemExit（fail loud）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'C1-S1.md'
            f.write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 习题\n\n'
                '### E1 {#exercise:B-1-S1-E1}\n\n习题甲。\n', encoding='utf-8')
            with self.assertRaises(SystemExit):
                _parse_items_blocks(f)

    def test_illustration_only_ok(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'C1-S1.md'
            f.write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 插图\n\n'
                '| id | figType | render | description |\n|---|---|---|---|\n'
                '| fig:B:B-C1-S1:图A | illustration |  | 插图A |\n', encoding='utf-8')
            blocks, fig_count = _parse_items_blocks(f, allow_vocab=True)
            self.assertEqual(blocks, [])
            self.assertGreater(fig_count, 0)

    def test_word_section_raises_for_math_book(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'C1-S1.md'
            f.write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 单词\n\n'
                '| id | word | ipa | pos | meaning |\n|---|---|---|---|---|\n'
                '| word:B:U1:fox | fox |  | n. | 狐狸 |\n', encoding='utf-8')
            with self.assertRaises(SystemExit):
                _parse_items_blocks(f, allow_vocab=False)

    def test_vocab_sections_ok_for_language_book(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'C1-S1.md'
            f.write_text(
                '---\nsectionId: B-C1-S1\n---\n\n## 单词\n\n'
                '| id | word | ipa | pos | meaning |\n|---|---|---|---|---|\n'
                '| word:B:U1:fox | fox |  | n. | 狐狸 |\n', encoding='utf-8')
            blocks, fig_count = _parse_items_blocks(f, allow_vocab=True)
            self.assertEqual(blocks, [])
            self.assertEqual(fig_count, 0)


class TestMathNorm(unittest.TestCase):
    def test_strip_dollar_and_space(self):
        self.assertEqual(_math_norm('$\\angle A$ = $60^\\circ$'), '∠A=60°')

    def test_triangle_and_angle(self):
        self.assertEqual(_math_norm('在 $\\triangle ABC$ 中，$\\angle A = 30^\\circ$'), '在△ABC中，∠A=30°')

    def test_inequality_symbols(self):
        self.assertEqual(_math_norm('$a \\le b$ 且 $c \\ge d$，$x \\neq 0$'), 'a≤b且c≥d，x≠0')

    def test_multiplication_and_degree(self):
        self.assertEqual(_math_norm('$2 \\times 3 = 6$，$90^\\circ$ 直角'), '2×3=6，90°直角')

    def test_parallel_perp_mid(self):
        self.assertEqual(_math_norm('$AB \\parallel CD$，$DE \\perp BC$'), 'AB∥CD，DE⊥BC')


class TestExtractH2BlockText(unittest.TestCase):
    def test_extract_middle_block(self):
        md = '# 第一章\n\n导语\n\n## 1. 三角形内角和定理\n\n内容A\n\n## 2. 图形的平移\n\n内容B\n\n## 3. 分式的性质\n\n内容C\n'
        text = _extract_h2_block_text(md, '图形的平移')
        self.assertIn('内容B', text)
        self.assertNotIn('内容A', text)
        self.assertNotIn('内容C', text)

    def test_extract_first_block(self):
        md = '# 第一章\n\n## 1. 三角形内角和定理\n\n内容A\n\n## 2. 图形的平移\n\n内容B\n'
        text = _extract_h2_block_text(md, '三角形内角和定理')
        self.assertIn('内容A', text)
        self.assertNotIn('内容B', text)

    def test_extract_last_block(self):
        md = '# 第一章\n\n## 1. 三角形内角和定理\n\n内容A\n\n## 2. 图形的平移\n\n内容B\n'
        text = _extract_h2_block_text(md, '图形的平移')
        self.assertIn('内容B', text)
        self.assertNotIn('内容A', text)

    def test_norm_title_match(self):
        md = '# 第一章\n\n## 1. 三角形内角和定理\n\n正文内容\n'
        text = _extract_h2_block_text(md, '三角形内角和定理')
        self.assertIn('正文内容', text)

    def test_missing_returns_empty(self):
        md = '# 第一章\n\n## 1. 三角形内角和定理\n\n内容\n'
        text = _extract_h2_block_text(md, '不存在的节')
        self.assertEqual(text, '')


class TestLoadConceptData(unittest.TestCase):
    """直接测 YAML 行级解析，防 alias/explanation 解析 bug 漏网。"""

    def _make_yaml(self, tmp: Path, content: str):
        d = tmp / 'graph' / 'entities' / 'concepts'
        d.mkdir(parents=True)
        (d / '数学.yaml').write_text(content, encoding='utf-8')

    def test_aliases_list_multiple_items(self):
        """aliases 多行列表正确解析。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._make_yaml(tmp, (
                '- id: concept:数学:勾股定理\n'
                '  type: Concept\n'
                '  title: 勾股定理\n'
                '  aliases:\n'
                '  - 毕达哥拉斯定理\n'
                '  - 商高定理\n'
                '  - 百牛定理\n'
                '  category: 数学定理\n'
                '  explanation: 直角三角形两直角边的平方和等于斜边的平方。\n'
                '  sourceRef: content/x.md\n'
            ))
            r = _load_concept_data(tmp, ['concept:数学:勾股定理'])
            self.assertIn('concept:数学:勾股定理', r)
            self.assertEqual(r['concept:数学:勾股定理']['title'], '勾股定理')
            self.assertEqual(
                r['concept:数学:勾股定理']['aliases'],
                ['毕达哥拉斯定理', '商高定理', '百牛定理'],
            )
            self.assertEqual(
                r['concept:数学:勾股定理']['explanation'],
                '直角三角形两直角边的平方和等于斜边的平方。',
            )

    def test_no_aliases_empty_list(self):
        """无 aliases 字段或空列表 → 空列表。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._make_yaml(tmp, (
                '- id: concept:数学:无理数\n'
                '  type: Concept\n'
                '  title: 无理数\n'
                '  aliases: []\n'
                '  explanation: 无限不循环小数叫做无理数。\n'
                '  sourceRef: content/x.md\n'
                '- id: concept:数学:有理数\n'
                '  type: Concept\n'
                '  title: 有理数\n'
                '  explanation: 整数和分数统称为有理数。\n'
                '  sourceRef: content/y.md\n'
            ))
            r = _load_concept_data(tmp, ['concept:数学:无理数', 'concept:数学:有理数'])
            self.assertEqual(r['concept:数学:无理数']['aliases'], [])
            self.assertEqual(r['concept:数学:有理数']['aliases'], [])  # 无 aliases 字段

    def test_multiline_explanation_joined(self):
        """explanation 多行续行（4 空格缩进）拼接为单行。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._make_yaml(tmp, (
                '- id: concept:数学:二次函数\n'
                '  type: Concept\n'
                '  title: 二次函数\n'
                '  aliases:\n'
                '  - 抛物线函数\n'
                '  explanation: 形如 y=ax²+bx+c（a≠0）的函数叫做二次函数。\n'
                '    其图象是一条抛物线，a 决定开口方向与大小。\n'
                '  sourceRef: content/x.md\n'
            ))
            r = _load_concept_data(tmp, ['concept:数学:二次函数'])
            d = r['concept:数学:二次函数']
            self.assertEqual(d['title'], '二次函数')
            self.assertEqual(d['aliases'], ['抛物线函数'])
            self.assertIn('形如 y=ax²+bx+c', d['explanation'])
            self.assertIn('其图象是一条抛物线', d['explanation'])
            # 用空格连接
            self.assertIn('。 其', d['explanation'])

    def test_missing_concept_default_values(self):
        """不存在的概念返回默认空值。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._make_yaml(tmp, '')
            r = _load_concept_data(tmp, ['concept:数学:不存在'])
            self.assertEqual(r['concept:数学:不存在']['title'], '')
            self.assertEqual(r['concept:数学:不存在']['aliases'], [])
            self.assertEqual(r['concept:数学:不存在']['explanation'], '')


class TestApplyConceptSourceRefNested(unittest.TestCase):
    """sourceRef 替换不命中嵌套字段（如 misconceptions 内含 sourceRef 字样）。"""

    def test_nested_sourceRef_not_rewritten(self):
        import importlib, reoutline_apply
        importlib.reload(reoutline_apply)
        text = (
            '- id: concept:数学:甲\n'
            '  type: Concept\n'
            '  sourceRef: content/OLD/S1.md\n'
            '  misconceptions:\n'
            '  - 误认为 sourceRef: content/OLD/S1.md 是答案\n'
            '  - 忽略了条件\n'
            '  explanation: 甲的解释\n'
        )
        concept_ref = {'concept:数学:甲': 'content/NEW/S2.md'}
        result = reoutline_apply.apply_concepts_source_remap(text, {}, concept_ref=concept_ref)
        # 顶层 sourceRef 被改写
        self.assertIn('  sourceRef: content/NEW/S2.md', result)
        # 嵌套 misconceptions 中的 sourceRef 字样保留原样
        self.assertIn('  - 误认为 sourceRef: content/OLD/S1.md 是答案', result)
        # 原顶层路径不应再出现
        self.assertNotIn('  sourceRef: content/OLD/S1.md', result)


class TestResolveOffsetOcr(unittest.TestCase):
    """reoutline_ocr.resolve_offset：imageOffset 缺失必抛（imageOffset 缺失处置 裁决）。"""

    def test_missing_raises_system_exit(self):
        ch = {'chapterId': 'B-C1', 'dir': 'chapters/C1'}
        with self.assertRaises(SystemExit) as cx:
            resolve_offset(ch)
        self.assertIn('imageOffset 未标定（imageOffset 缺失处置）', str(cx.exception))

    def test_explicit_zero_ok(self):
        ch = {'chapterId': 'B-C1', 'imageOffset': 0}
        self.assertEqual(resolve_offset(ch), 0)

    def test_explicit_positive_ok(self):
        ch = {'chapterId': 'B-C1', 'imageOffset': 6}
        self.assertEqual(resolve_offset(ch), 6)


class TestResolveBookOffsetPropose(unittest.TestCase):
    """reoutline_propose.resolve_book_offset：imageOffset 缺失必抛（imageOffset 缺失处置 裁决）。"""

    def test_missing_raises_system_exit(self):
        meta = {'textbookId': 'BSD-7-1-Math'}
        with self.assertRaises(SystemExit) as cx:
            resolve_book_offset(meta)
        self.assertIn('imageOffset 未标定（imageOffset 缺失处置）', str(cx.exception))

    def test_explicit_zero_ok(self):
        meta = {'textbookId': 'B', 'imageOffset': 0}
        self.assertEqual(resolve_book_offset(meta), 0)

    def test_explicit_positive_ok(self):
        meta = {'textbookId': 'B', 'imageOffset': 4}
        self.assertEqual(resolve_book_offset(meta), 4)


class TestProbeNormTitle(unittest.TestCase):
    """节标题归一（首页节标题探针共用 reoutline_propose.norm_title，与三档序数剥离同语义）。"""

    def test_number_dot_space(self):
        self.assertEqual(norm_title('2. 等腰三角形'), '等腰三角形')

    def test_chinese_ordinal(self):
        self.assertEqual(norm_title('一、相交线'), '相交线')

    def test_no_number(self):
        self.assertEqual(norm_title('三角形内角和'), '三角形内角和')

    def test_leading_space(self):
        self.assertEqual(norm_title('  5.  光的反射'), '光的反射')


class TestTitleProbeWarn(unittest.TestCase):
    """首页节标题探针：含标题→无 WARN；不含→打印 WARN。"""

    def test_title_found_no_warn(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # 直接调用内部逻辑等价形式：构造首页文本含标题
            title = '2. 等腰三角形'
            core = norm_title(title)
            first_page_text = '等腰三角形的性质\n定义：两边相等的三角形...'
            if core and core not in first_page_text:
                print(f'[reoutline] WARN C1-S2: 首页未探到节标题「{title}」（检查 imageOffset 标定）')
        self.assertNotIn('[reoutline] WARN', buf.getvalue())

    def test_title_missing_prints_warn(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            title = '2. 等腰三角形'
            core = norm_title(title)
            first_page_text = '全等三角形的判定\nSSS SAS ASA...'
            if core and core not in first_page_text:
                print(f'[reoutline] WARN C1-S2: 首页未探到节标题「{title}」（检查 imageOffset 标定）')
        out = buf.getvalue()
        self.assertIn('[reoutline] WARN', out)
        self.assertIn('首页未探到节标题', out)
        self.assertIn('等腰三角形', out)
        self.assertIn('检查 imageOffset 标定', out)


class TestNormalizeChapterIds(unittest.TestCase):
    """PG 非数字章后缀（TS/APP）→ 顺延数字章号（ZTB-7-2-Geo 首例暴露）。"""

    def test_ts_app_normalized(self):
        book = {'chapters': [
            {'id': 'B-C1', 'sections': [{'id': 'B-C1-S1'}]},
            {'id': 'B-TS', 'sections': [{'id': 'B-TS-S1'}]},
            {'id': 'B-APP', 'sections': [{'id': 'B-APP-S1'}]},
        ]}
        mapping = normalize_chapter_ids(book, 'B')
        self.assertEqual(mapping, {'B-TS': 'B-C2', 'B-APP': 'B-C3'})

    def test_numeric_unchanged(self):
        book = {'chapters': [{'id': 'B-C7', 'sections': []}]}
        self.assertEqual(normalize_chapter_ids(book, 'B'), {})


class TestPgPageSpace(unittest.TestCase):
    """PG 页空间声明与归一（2026-09-15 P2：页空间逐书不一致，fail-loud）。"""

    def test_load_requires_file_and_valid_value(self):
        """缺 page_space.json 或声明值非法均应 SystemExit，合法值原样返回。"""
        from reoutline_propose import load_pg_page_space
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            with self.assertRaises(SystemExit):  # 声明文件缺失
                load_pg_page_space(p, 'X-7-1-Math')
            (p / 'page_space.json').write_text('{"X-7-1-Math": "wrong"}', encoding='utf-8')
            with self.assertRaises(SystemExit):  # 值非法
                load_pg_page_space(p, 'X-7-1-Math')
            (p / 'page_space.json').write_text('{"X-7-1-Math": "image"}', encoding='utf-8')
            self.assertEqual(load_pg_page_space(p, 'X-7-1-Math'), 'image')

    def test_normalize_subtracts_offset_and_fails_on_nonpositive(self):
        """page/image 各端减 offset 归一，无页码节原样保留，非正页码即 SystemExit。"""
        from reoutline_propose import normalize_pg_ranges
        chs = [{'id': 'B-C1', 'pageRange': [6, 37], 'sections': [
            {'id': 'B-C1-S1', 'pageRange': [7, 16]},
            {'id': 'B-C1-S2', 'pageRange': None},
        ]}]
        normalize_pg_ranges(chs, 5)
        self.assertEqual(chs[0]['pageRange'], [1, 32])
        self.assertEqual(chs[0]['sections'][0]['pageRange'], [2, 11])
        self.assertIsNone(chs[0]['sections'][1]['pageRange'])  # 无页码节原样保留
        with self.assertRaises(SystemExit):  # 归一后出现非正页码 → 声明/offset 有误
            normalize_pg_ranges([{'id': 'B-C1', 'pageRange': [3, 9], 'sections': []}], 5)


class TestResolveSid(unittest.TestCase):
    """PG 节 id 非 S<n> 构词（UUID 脏数据）时按标题唯一匹配回填。"""

    def test_standard_id_passthrough(self):
        """标准 S<n> 构词直通返回，不触发标题匹配。"""
        from reoutline_propose import resolve_s_id
        sid, by_match = resolve_s_id({'id': 'B-C1-S3', 'title': 'x'}, [])
        self.assertEqual((sid, by_match), ('S3', False))

    def test_uuid_title_match_and_fail_louds(self):
        """UUID 脏 id 按标题唯一匹配回填（含字序颠倒容错），无匹配/多命中 SystemExit。"""
        from reoutline_propose import resolve_s_id
        fm = [{'id': 'S5', 'title': '回顾与思考'}, {'id': 'S6', 'title': '复习题'}]
        sid, by_match = resolve_s_id(
            {'id': '12dcf915-9a72-49dd-8f9b-338f9c3ab7bd', 'title': '回顾与思考'}, fm)
        self.assertEqual((sid, by_match), ('S5', True))
        # 字序颠倒容错（2026-09-15 实证：PG「思考与回顾」vs 书页「回顾与思考」笔误）
        sid, by_match = resolve_s_id(
            {'id': '3edca033-71c6-441f-8e66-c4594238084a', 'title': '思考与回顾'}, fm)
        self.assertEqual((sid, by_match), ('S5', True))
        with self.assertRaises(SystemExit):  # 标题无匹配
            resolve_s_id({'id': 'deadbeef-0001', 'title': '不存在的节'}, fm)
        with self.assertRaises(SystemExit):  # 标题多命中
            resolve_s_id({'id': 'deadbeef-0002', 'title': '回顾与思考'}, [
                {'id': 'S5', 'title': '回顾与思考'}, {'id': 'S4', 'title': '回顾与思考'}])


if __name__ == '__main__':
    unittest.main()
