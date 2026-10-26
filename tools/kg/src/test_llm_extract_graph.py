#!/usr/bin/env python3
"""llm_extract_graph --from-raw 纯逻辑测试：raw 读取校验、复用/丢弃/黑名单、续跑跳过、不调 LLM。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import llm_extract_graph as m  # noqa: E402

SID = 'BSDU-3-1-Math-C1-S1'


def make_section(root: Path) -> Path:
    p = root / 'content/三年级/上册/数学/BSDU-3-1-Math/chapters/C1/sections/S1.md'
    p.parent.mkdir(parents=True)
    p.write_text(f'---\nsectionId: {SID}\npageRange: [2, 3]\n---\n# 分数的初步认识\n\n把一个月饼平均分成 2 份……\n',
                 encoding='utf-8')
    return p


def write_raw(payload: dict) -> Path:
    f = m.raw_dir('BSDU-3-1-Math') / f'{SID}.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return f


def no_client():
    raise AssertionError('from-raw 模式不得调用 make_client')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._knowledge, self._make, self._argv = m.KNOWLEDGE, m.make_client, sys.argv
        m.KNOWLEDGE = self.root
        m.make_client = no_client

    def tearDown(self):
        m.KNOWLEDGE, m.make_client, sys.argv = self._knowledge, self._make, self._argv
        self.tmp.cleanup()


class ResolveSectionIdTest(unittest.TestCase):
    def test_frontmatter_first_then_path(self):
        p = Path('/x/content/三年级/上册/数学/BSDU-3-1-Math/chapters/C2/sections/S4.md')
        self.assertEqual(m.resolve_section_id(p, {'sectionId': 'X-C9-S9'}, 'BSDU-3-1-Math'), 'X-C9-S9')
        self.assertEqual(m.resolve_section_id(p, {}, 'BSDU-3-1-Math'), 'BSDU-3-1-Math-C2-S4')
        self.assertEqual(m.resolve_section_id(Path('/x/a.md'), {}, 'T'), '')


class LoadRawTest(Base):
    def test_missing_file_fails_loud(self):
        with self.assertRaises(FileNotFoundError):
            m.load_raw('BSDU-3-1-Math', SID)

    def test_section_id_mismatch_fails(self):
        write_raw({'sectionId': 'BSDU-3-1-Math-C9-S9', 'concepts': []})
        with self.assertRaises(ValueError):
            m.load_raw('BSDU-3-1-Math', SID)

    def test_only_concepts_kept(self):
        write_raw({'sectionId': SID, 'concepts': [], 'words': [{'word': 'apple'}]})
        self.assertEqual(m.load_raw('BSDU-3-1-Math', SID), {'concepts': []})


class ProcessSectionTest(Base):
    def test_reuse_drop_uncovered_and_junk(self):
        sec = make_section(self.root)
        write_raw({'sectionId': SID, 'concepts': [
            {'title': '分数', 'covered': True},
            {'title': '几分之一', 'covered': True, 'explanation': '把整体平均分成几份，其中一份是几分之一。'},
            {'title': '顺带提及', 'covered': False},
            {'title': '练一练', 'covered': True},
        ]})
        cache = {'数学': {'分数': 'concept:数学:分数'}}
        r = m.process_section(sec, client=None, model='', sleep_s=0, concept_cache=cache, from_raw=True)
        self.assertEqual([c['id'] for c in r['concepts']], ['concept:数学:几分之一'])
        self.assertEqual(r['concepts'][0]['sourceRef'], 'content/三年级/上册/数学/BSDU-3-1-Math/chapters/C1/sections/S1.md')
        self.assertEqual(sorted(x['from'] for x in r['relations']), ['concept:数学:几分之一', 'concept:数学:分数'])
        self.assertTrue(all(x['type'] == 'covered_by' and x['to'] == SID for x in r['relations']))
        self.assertEqual(r['items'], [])


class LoadExistingConceptsTest(Base):
    def test_title_only_aliases_not_merged(self):
        # 门 C 错例：三年级「估算」经别名并进初中「无理数的估算」。复用只认同名标题
        f = self.root / 'graph/entities/concepts/数学.yaml'
        f.parent.mkdir(parents=True)
        f.write_text('- id: concept:数学:无理数的估算\n  title: 无理数的估算\n  aliases:\n    - 估算\n', encoding='utf-8')
        self.assertEqual(m.load_existing_concepts('数学'), {'无理数的估算': 'concept:数学:无理数的估算'})


class MainTest(Base):
    def run_main(self, sec: Path, *extra: str) -> int:
        sys.argv = ['llm_extract_graph.py', str(sec), '--from-raw', *extra]
        return m.main()

    def test_writes_extract_without_llm(self):
        sec = make_section(self.root)
        write_raw({'sectionId': SID, 'concepts': [{'title': '几分之一', 'covered': True}]})
        self.assertEqual(self.run_main(sec), 0)
        out = json.loads((m.extract_dir('BSDU-3-1-Math') / f'{SID}.json').read_text(encoding='utf-8'))
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['relations'], [{'type': 'covered_by', 'from': 'concept:数学:几分之一', 'to': SID}])

    def test_existing_extract_skipped_even_without_raw(self):
        sec = make_section(self.root)
        out = m.extract_dir('BSDU-3-1-Math') / f'{SID}.json'
        out.parent.mkdir(parents=True)
        out.write_text('{"status": "ok"}', encoding='utf-8')
        self.assertEqual(self.run_main(sec), 0)
        self.assertEqual(out.read_text(encoding='utf-8'), '{"status": "ok"}')

    def test_missing_raw_exit_1(self):
        sec = make_section(self.root)
        self.assertEqual(self.run_main(sec), 1)


if __name__ == '__main__':
    unittest.main()
