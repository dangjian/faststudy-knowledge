import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadGraph, loadContentItems, deriveStructure } from '../src/load.js'

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures')

test('loadGraph 加载 fixture 实体与关系', () => {
  const g = loadGraph(fixtures)
  assert.ok(g.entities.find(e => e.id === 'concept:english:be-verb'))
  assert.ok(g.relations.length >= 1)
  const pre = g.relations.find(r => r.type === 'prerequisite')
  assert.equal(pre?.to, 'concept:english:be-verb')
})

test('entityFiles 记录 id->路径', () => {
  const g = loadGraph(fixtures)
  assert.ok(g.entityFiles.get('concept:english:be-verb')?.endsWith('be-verb.yaml'))
})

test('deriveStructure: 从书级 index.md front-matter 派生 Textbook/Chapter/Section 实体', () => {
  const g = loadGraph(fixtures)
  const tb = g.entities.find(e => e.id === 'PEP-7-2-English')
  assert.equal(tb?.type, 'Textbook')
  assert.equal((tb as { standardEdition?: string }).standardEdition, '2022版')
  const ch = g.entities.find(e => e.id === 'PEP-7-2-English-C1')
  assert.equal(ch?.type, 'Chapter')
  const sec = g.entities.find(e => e.id === 'PEP-7-2-English-C1-S1')
  assert.equal(sec?.type, 'Section')
  assert.equal((sec as { chapterId?: string }).chapterId, 'PEP-7-2-English-C1')
  assert.match(g.entityFiles.get('PEP-7-2-English-C1-S1') ?? '', /index\.md$/)
})

test('loadContentItems: 从 section md 文末词书区块加载四类实体（v4）', () => {
  const g = loadGraph(fixtures)
  const word = g.entities.find(e => e.type === 'Word')
  assert.ok(word, 'section md 词书区块中的 Word 应被加载')
  assert.equal(g.entities.find(e => e.type === 'Figure'), undefined, 'Figure 已退役')
  assert.equal(g.entities.find(e => e.type === 'ExamModel'), undefined, 'ExamModel 已退役')
  assert.match(g.entityFiles.get(word!.id) ?? '', /content\/.*\/sections\/S1\.md$/)
})

test('loadContentItems: 章 index 的词书区块也被扫描（v4）', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'kg-load-test-'))
  try {
    mkdirSync(join(tmp, 'content/X/chapters/C1'), { recursive: true })
    writeFileSync(join(tmp, 'content/X/index.md'), '---\ntextbookId: T-1\ntitle: T\ngrade: "7"\nterm: "1"\nsubject: 数学\npublisher: P\ntotalPages: 1\norigin: textbook\nchapters:\n  - id: C1\n    title: 第一章\n    order: 1\n    pageRange: [1, 2]\n---\n')
    writeFileSync(join(tmp, 'content/X/chapters/C1/index.md'), '---\nchapterId: T-1-C1\n---\n\n## 汉字\n\n| id | char | pinyin | definition | example |\n| --- | --- | --- | --- | --- |\n| character:T-1-C1:春 | 春 | chūn | 季节 | 春天 |\n')
    const { entities } = loadContentItems(tmp)
    const ch = entities.find(e => e.type === 'Character')
    assert.ok(ch, '章 index 的汉字区块应被加载')
    assert.match(String(ch!.sourceRef), /chapters\/C1\/index\.md$/)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('ontology: 每个实体类型声明 storage(content|graph|derived)', () => {
  const g = loadGraph(fixtures)
  for (const [name, def] of Object.entries(g.ontology.entity_types)) {
    assert.ok(['content', 'graph', 'derived'].includes((def as { storage?: string }).storage ?? ''), `${name} 缺 storage`)
  }
})

test('deriveStructure: 混合格式(部分 chapter 缺 id)抛含文件路径的错误', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'kg-load-test-'))
  try {
    mkdirSync(join(tmp, 'content/X'), { recursive: true })
    writeFileSync(join(tmp, 'content/X/index.md'), [
      '---',
      'textbookId: T-1',
      'title: 混合',
      "grade: '7'",
      "term: '1'",
      'subject: Math',
      'publisher: PEP',
      'totalPages: 10',
      'chapters:',
      '  - id: C1',
      '    title: 新格式章',
      '    order: 1',
      '    pageRange: [1, 5]',
      "  - chapter: '2'",
      '    title: 旧格式章',
      '    pageRange: [6, 10]',
      '---',
      '',
      '# 混合',
    ].join('\n'))
    assert.throws(() => deriveStructure(tmp), /混合格式.*index\.md/)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('deriveStructure: 新格式字段畸形(缺 pageRange)抛含路径的 schema 校验错误', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'kg-load-test-'))
  try {
    mkdirSync(join(tmp, 'content/X'), { recursive: true })
    writeFileSync(join(tmp, 'content/X/index.md'), [
      '---',
      'textbookId: T-1',
      'title: 畸形',
      "grade: '7'",
      "term: '1'",
      'subject: Math',
      'publisher: PEP',
      'totalPages: 10',
      'chapters:',
      '  - id: C1',
      '    title: 缺页码的章',
      '    order: 1',
      '---',
      '',
      '# 畸形',
    ].join('\n'))
    assert.throws(() => deriveStructure(tmp), /schema 校验失败.*index\.md/)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})
