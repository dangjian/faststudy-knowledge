import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { parse } from 'yaml'
import { writeExtract, ingest, type Extractor, type ExtractResult } from '../src/ingest.js'
import { parseItemsMd } from '../src/items_md.js'
import type { Entity } from '../src/schema/types.js'

function tmpRoot() {
  const root = mkdtempSync(join(tmpdir(), 'kg-'))
  return {
    contentDir: join(root, 'content'),
    graphDir: join(root, 'graph'),
    skillDir: join(root, 'skills'),
  }
}

const fakeResult: ExtractResult = {
  prose: '# S1\n正文',
  concepts: [{ id: 'concept:english:foo', type: 'Concept', subject: 'english', title: 'Foo', explanation: 'x' }],
  items: [
    { id: 'word:T:U1:bar', type: 'Word', word: 'bar', meaning: '巴' },
  ],
  relations: [{ type: 'demonstrates', from: 'word:T:U1:bar', to: 'concept:english:foo' }],
}

const sec = { sectionId: 'PEP-7-2-English-C1-S1', pageRange: [1, 2] as [number, number], images: [] }

test('writeExtract: 词书区块追加到 section md 文末,concepts 追加学科聚合文件（v4）', () => {
  const opts = tmpRoot()
  writeExtract(sec, fakeResult, opts)
  // content:正文 + 文末词书区块,不再有独立 items 目录
  const secFile = join(opts.contentDir, 'PEP-7-2-English-C1-S1.md')
  assert.ok(existsSync(secFile))
  const src = readFileSync(secFile, 'utf8')
  assert.match(src, /^# S1/m)
  const doc = parseItemsMd(src, secFile)
  assert.equal(doc.sectionId, 'PEP-7-2-English-C1-S1')
  assert.equal((doc.tables['Word'] as { id: string }[])[0]!.id, 'word:T:U1:bar')
  // concepts:学科聚合数组
  const conceptFile = join(opts.graphDir, 'entities/concepts/english.yaml')
  assert.ok(existsSync(conceptFile))
  const concepts = parse(readFileSync(conceptFile, 'utf8')) as Entity[]
  assert.ok(Array.isArray(concepts))
  assert.ok(concepts.some(c => c.id === 'concept:english:foo'))
  // relations
  const rel = readFileSync(join(opts.graphDir, 'relations/demonstrates.yaml'), 'utf8')
  assert.match(rel, /bar/)
})

test('writeExtract 幂等:词书区块不重复追加,concept 同 id 不重复', () => {
  const opts = tmpRoot()
  writeExtract(sec, fakeResult, opts)
  writeExtract(sec, { ...fakeResult, prose: '' }, opts)   // prose 为空 = 节文件已由上游落盘
  const secFile = join(opts.contentDir, 'PEP-7-2-English-C1-S1.md')
  const src = readFileSync(secFile, 'utf8')
  assert.equal(src.match(/^## 单词$/gm)?.length, 1, '词书区块只出现一次')
  const conceptFile = join(opts.graphDir, 'entities/concepts/english.yaml')
  let concepts = parse(readFileSync(conceptFile, 'utf8')) as Entity[]
  assert.equal(concepts.length, 1)
  // 追加新概念后按 id 码点排序
  writeExtract(sec, {
    ...fakeResult,
    prose: '',
    concepts: [{ id: 'concept:english:apple', type: 'Concept', subject: 'english', title: 'Apple' }],
  }, opts)
  concepts = parse(readFileSync(conceptFile, 'utf8')) as Entity[]
  assert.deepEqual(concepts.map(c => c.id), ['concept:english:apple', 'concept:english:foo'])
})

test('writeExtract force:词书区块整段替换而非重复', () => {
  const opts = tmpRoot()
  writeExtract(sec, fakeResult, opts)
  writeExtract(sec, {
    ...fakeResult,
    prose: '',
    items: [{ id: 'word:T:U1:bar', type: 'Word', word: 'bar-v2', meaning: '巴2' }],
  }, { ...opts, force: true })
  const src = readFileSync(join(opts.contentDir, 'PEP-7-2-English-C1-S1.md'), 'utf8')
  assert.equal(src.match(/^## 单词$/gm)?.length, 1)
  assert.match(src, /bar-v2/)
  assert.doesNotMatch(src, /\| bar \|/)
})

test('writeExtract force:同 id concept 替换而非重复', () => {
  const opts = tmpRoot()
  writeExtract(sec, fakeResult, opts)
  writeExtract(sec, {
    ...fakeResult,
    concepts: [{ id: 'concept:english:foo', type: 'Concept', subject: 'english', title: 'Foo v2' }],
  }, { ...opts, force: true })
  const concepts = parse(readFileSync(join(opts.graphDir, 'entities/concepts/english.yaml'), 'utf8')) as { id: string; title: string }[]
  assert.equal(concepts.length, 1)
  assert.equal(concepts[0]!.title, 'Foo v2')
})

test('writeExtract: 未知 item 类型抛错', () => {
  const opts = tmpRoot()
  const bad: ExtractResult = {
    ...fakeResult,
    items: [{ id: 'x:1', type: 'Alien' } as unknown as Entity],
  }
  assert.throws(() => writeExtract(sec, bad, opts), /Alien.*x:1|x:1.*Alien/)
})

test('writeExtract: Figure 已退役,随抽取产物出现即抛错（v4）', () => {
  const opts = tmpRoot()
  const bad: ExtractResult = {
    ...fakeResult,
    items: [{ id: 'fig:T:U1:1', type: 'Figure', figType: 'illustration' } as unknown as Entity],
  }
  assert.throws(() => writeExtract(sec, bad, opts), /Figure/)
})

test('writeExtract: YAML 1.1 布尔保留词字符串写盘带引号', () => {
  const opts = tmpRoot()
  writeExtract(sec, {
    ...fakeResult,
    concepts: [{ id: 'concept:english:yes', type: 'Concept', subject: 'english', title: 'Yes' }],
    items: [{ id: 'word:T:U1:no', type: 'Word', word: 'No', meaning: '不' }],
  }, opts)
  const conceptText = readFileSync(join(opts.graphDir, 'entities/concepts/english.yaml'), 'utf8')
  assert.match(conceptText, /'Yes'/)
})

test('ingest 用注入 extractor 跑通编排', async () => {
  const opts = tmpRoot()
  const extractor: Extractor = { async extract() { return fakeResult } }
  await ingest([sec], extractor, opts)
  assert.match(readFileSync(join(opts.contentDir, 'PEP-7-2-English-C1-S1.md'), 'utf8'), /^## 单词$/m)
})

test('writeExtract -> parseItemsMd 往返:管道转义与多值单元格', () => {
  const opts = tmpRoot()
  writeExtract(sec, {
    ...fakeResult,
    items: [
      { id: 'sentence:T:U1:s1', type: 'Sentence', english: ['Hello', 'world'], cn: '你好|世界' },
    ],
  }, opts)
  const secFile = join(opts.contentDir, 'PEP-7-2-English-C1-S1.md')
  const doc = parseItemsMd(readFileSync(secFile, 'utf8'), secFile)
  assert.deepEqual(doc.tables['Sentence']![0], { type: 'Sentence', id: 'sentence:T:U1:s1', english: ['Hello', 'world'], cn: '你好|世界' })
})
