import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseItemsMd, parseSupplement, renderItemsMd } from '../src/items_md.js'

const SAMPLE = [
  '---',
  'sectionId: X-C1-S1',
  '---',
  '',
  '# Section A',
  '教材原文。',
  '',
  '## 单词',
  '',
  '| id | word | ipa | pos | meaning |',
  '| --- | --- | --- | --- | --- |',
  '| word:X:U1:hello | hello | /həˈləʊ/ | int. | 喂；你好 |',
  '',
  '## 句子',
  '',
  '| id | english | cn |',
  '| --- | --- | --- |',
  '| sentence:X:U1:s1 | Hello<br>world | 你好，世界 |',
  '',
  '## 插图',
  '',
  '| id | figType | render | description |',
  '| --- | --- | --- | --- |',
  '| fig:X:C1-S1:图 | illustration |  | 描述 |',
  '',
].join('\n')

test('parseSupplement: 无 frontmatter 时全文为 body', () => {
  const doc = parseSupplement('1. 第一步\n2. 第二步\n')
  assert.deepEqual(doc.frontmatter, {})
  assert.equal(doc.body, '1. 第一步\n2. 第二步')
})

test('parseSupplement: 仅 frontmatter 无正文时 body 为空串', () => {
  const doc = parseSupplement('---\nsectionId: X-C1-S1\n---\n')
  assert.equal(doc.frontmatter.sectionId, 'X-C1-S1')
  assert.equal(doc.body, '')
})

test('parseItemsMd: 词书四类区块解析（原文跳过/单元格转义/<br>数组）', () => {
  const doc = parseItemsMd(SAMPLE, 'X/chapters/C1/sections/S1.md')
  assert.equal(doc.sectionId, 'X-C1-S1')
  assert.equal(doc.tables['Word']![0]!.meaning, '喂；你好')
  assert.deepEqual(doc.tables['Sentence']![0]!.english, ['Hello', 'world'])
  assert.equal(doc.tables['Character'], undefined)
})

test('parseItemsMd: 插图区块降级为纯文本图注，不派生实体（v4）', () => {
  const doc = parseItemsMd(SAMPLE, 'X/chapters/C1/sections/S1.md')
  assert.equal(doc.tables['Figure'], undefined)
})

test('parseItemsMd: 章 index 无 sectionId front-matter 时可缺省', () => {
  const doc = parseItemsMd('---\nchapterId: X-C1\n---\n\n## 汉字\n\n| id | char | pinyin | definition | example |\n| --- | --- | --- | --- | --- |\n| character:X:C1:春 | 春 | chūn | 季节 | 春天 |\n', 'X/chapters/C1/index.md')
  assert.equal(doc.sectionId, undefined)
  assert.equal(doc.tables['Character']![0]!.char, '春')
})

test('parseItemsMd: 教材原文小节标题不干扰扫描（含 ## 习题6.2 这类原文标题）', () => {
  const withProse = SAMPLE.replace('## 插图', '## 习题6.2\n\n原文小节。\n\n## 插图')
  const doc = parseItemsMd(withProse, 'X/chapters/C1/sections/S1.md')
  assert.equal(doc.tables['Word']!.length, 1)
})

test('parseItemsMd: 管道单元格转义还原', () => {
  const doc = parseItemsMd('## 短语\n\n| id | en | cn |\n| --- | --- | --- |\n| phrase:X:U1:p1 | a \\| b | 甲｜乙 |\n', 'X.md')
  assert.equal(doc.tables['Phrase']![0]!.en, 'a | b')
})

test('parseItemsMd: 含 ## 习题 段即抛错（刷题层已移除，历史文件回流 fail-loud）', () => {
  const stale = SAMPLE.replace('## 单词', '## 习题\n\n习题甲。\n\n## 单词')
  assert.throws(() => parseItemsMd(stale, 'X/chapters/C1/sections/S1.md'), /## 习题/)
})

test('renderItemsMd: 区块渲染（写端与解析端同构，无 front-matter）', () => {
  const md = renderItemsMd({
    Word: [{ id: 'word:X:U1:hello', word: 'hello', ipa: '/həˈləʊ/', pos: 'int.', meaning: '喂；你好' }],
    Sentence: [{ id: 'sentence:X:U1:s1', english: ['Hello', 'world'], cn: '你好，世界' }],
  })
  assert.doesNotMatch(md, /^---/m, 'v4 区块文本不再携带 front-matter')
  const doc = parseItemsMd(md, 'X/chapters/C1/sections/S1.md')
  assert.equal(doc.tables['Word']![0]!.meaning, '喂；你好')
  assert.deepEqual(doc.tables['Sentence']![0]!.english, ['Hello', 'world'])
  assert.equal(md.includes('习题'), false)
})
