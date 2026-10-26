import { test } from 'node:test'
import assert from 'node:assert/strict'
import { lint, checkSectionTocAgree, checkBookIndexRequired, checkSectionConceptMin, checkSectionConceptMinJunior, checkCoveredByAnchor } from '../src/lint.js'
import { loadGraph } from '../src/load.js'
import type { LintReport, LintFinding } from '../src/schema/types.js'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync, writeFileSync, mkdtempSync, mkdirSync, rmSync, cpSync } from 'node:fs'
import { tmpdir } from 'node:os'

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures')

test('lint 合法 fixture 无 error', () => {
  const r = lint(loadGraph(fixtures))
  assert.equal(r.errors.length, 0)
})

test('rule 6 ontology-drift 检测未注册类型', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'x', type: 'Alien' } as never)
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'ontology-drift'))
})

test('rule 3 referential-integrity 检测悬空端点', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'prerequisite', from: 'concept:ghost', to: 'concept:english:be-verb' })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'referential-integrity' && f.ref === 'concept:ghost'))
})

test('rule 2 relation-endpoint 检测 demonstrates 方向错误', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'demonstrates', from: 'concept:english:be-verb', to: 'concept:english:animal-vocab' })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'relation-endpoint'))
})

test('rule 5 ID-uniqueness 检测重复', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ ...g.entities[0]! })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'ID-uniqueness'))
})

test('rule 4 cycle: prerequisite 环被检测', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'prerequisite', from: 'concept:english:be-verb', to: 'concept:english:present-continuous' })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'cycle'))
})

test('rule 4 cycle: part_of 互指对被检测', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'part_of', from: 'concept:english:be-verb', to: 'concept:english:present-continuous' })
  g.relations.push({ type: 'part_of', from: 'concept:english:present-continuous', to: 'concept:english:be-verb' })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'cycle' && f.message.startsWith('part_of')))
})

test('rule 4 cycle: related 边不触发环检测', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'related', from: 'concept:english:be-verb', to: 'concept:english:present-continuous' })
  g.relations.push({ type: 'related', from: 'concept:english:present-continuous', to: 'concept:english:be-verb' })
  const r = lint(g)
  assert.equal(r.errors.some(f => f.rule === 'cycle'), false)
})

test('rule 14 prerequisite-downstream: 无争议下游边被检测', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'prerequisite', from: 'concept:数学:二次根式', to: 'concept:数学:二次根式的乘法法则' })
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'prerequisite-downstream'))
})

test('rule 14 prerequisite-downstream: 挂起边(在 suspended 清单)不报', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'prerequisite', from: 'concept:数学:二次根式', to: 'concept:数学:二次根式的乘法法则' })
  const suspended = new Set(['concept:数学:二次根式|concept:数学:二次根式的乘法法则'])
  const r = lint(g, suspended)
  assert.equal(r.errors.some(f => f.rule === 'prerequisite-downstream'), false)
})

test('rule 7 orphan: 未覆盖概念产生 warning', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'concept:lonely', type: 'Concept', subject: 'english', title: 'Lonely' } as never)
  const r = lint(g)
  assert.ok(r.warnings.some(f => f.rule === 'orphan' && f.ref === 'concept:lonely'))
})

test('rule 8 sourceRef: 缺 sourceRef 产生 warning', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'concept:x', type: 'Concept', subject: 'english', title: 'X' } as never)
  const r = lint(g)
  assert.ok(r.warnings.some(f => f.rule === 'sourceRef' && f.ref === 'concept:x'))
})

test('rule 10 layer-placement: content 层实体落在 graph/ 报 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'word:bad:misplaced', type: 'Word', word: 'bad', meaning: '错位' } as never)
  g.entityFiles.set('word:bad:misplaced', '/repo/graph/entities/rogue/word.yaml')
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'layer-placement' && f.ref === 'word:bad:misplaced'))
})

test('rule 10 layer-placement: derived 实体以 graph 源文件存在报 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'FAKE-TB', type: 'Textbook', title: 't', grade: '7', term: '1', subject: '数学', publisher: 'X', totalPages: 1 } as never)
  g.entityFiles.set('FAKE-TB', '/repo/graph/entities/structure/FAKE-TB.yaml')
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'layer-placement' && f.ref === 'FAKE-TB'))
})

test('rule 10 layer-placement: graph 层实体落在 content items 报 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({ id: 'concept:数学:错位', type: 'Concept', subject: '数学', title: '错位' } as never)
  g.entityFiles.set('concept:数学:错位', '/repo/content/七年级/下册/数学/X/items/C1-S1.yaml')
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'layer-placement' && f.ref === 'concept:数学:错位'))
})

test('rule 10 layer-placement: ontology 缺 storage 声明报 error 且同类型只报一次', () => {
  const g = loadGraph(fixtures)
  delete (g.ontology.entity_types['Concept'] as { storage?: string }).storage
  const r = lint(g)
  const hits = r.errors.filter(f => f.rule === 'layer-placement' && f.message.includes('缺 storage 声明'))
  assert.equal(hits.length, 1)
})

test('rule 12 summary-height: 超长 explanation 与步骤化 explanation 报 warning 且不增 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({
    id: 'concept:数学:话痨概念', type: 'Concept', subject: '数学', title: '话痨',
    explanation: '很长的正文。'.repeat(50),
  } as never)
  g.entities.push({
    id: 'concept:数学:步骤概念', type: 'Concept', subject: '数学', title: '步骤',
    explanation: '解题步骤:\n1. 移项\n2. 合并同类项\n3. 系数化为 1',
  } as never)
  const r = lint(g)
  assert.ok(r.warnings.some(f => f.rule === 'summary-height' && f.ref === 'concept:数学:话痨概念' && f.message.includes('长度')))
  assert.ok(r.warnings.some(f => f.rule === 'summary-height' && f.ref === 'concept:数学:步骤概念' && f.message.includes('步骤化信号')))
  // informational：summary-height 只进 warnings,不进 errors
  assert.equal(r.errors.filter(f => f.rule === 'summary-height').length, 0)
})

test('rule 12 summary-height: 正常短 summary 不报', () => {
  const r = lint(loadGraph(fixtures))
  assert.equal(r.warnings.filter(f => f.rule === 'summary-height').length, 0)
})

test('rule 12 summary-height: 同类超 10 条截断为 …等共 N 条', () => {
  const g = loadGraph(fixtures)
  for (let i = 0; i < 12; i++) {
    g.entities.push({
      id: `concept:数学:啰嗦${i}`, type: 'Concept', subject: '数学', title: `啰嗦${i}`,
      explanation: `第一步：做这个\n第二步：做那个（${i}）`,
    } as never)
  }
  const r = lint(g)
  const hits = r.warnings.filter(f => f.rule === 'summary-height')
  assert.equal(hits.filter(f => f.ref).length, 10)
  assert.ok(hits.some(f => f.message.includes('等共 12 条')))
})

test('rule 13 confidence: <0.7 报 warning 且不增 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({
    id: 'concept:数学:低置信', type: 'Concept', subject: '数学', title: '低置信', confidence: 0.6,
  } as never)
  const before = lint(loadGraph(fixtures)).errors.length
  const r = lint(g)
  assert.ok(r.warnings.some(f => f.rule === 'confidence' && f.ref === 'concept:数学:低置信' && f.message.includes('< 0.7')))
  assert.equal(r.errors.filter(f => f.rule === 'confidence').length, 0)
  assert.equal(r.errors.length, before)  // errors 数不受影响
})

test('rule 13 confidence: ≥0.7 不报', () => {
  const g = loadGraph(fixtures)
  g.entities.push({
    id: 'concept:数学:高置信', type: 'Concept', subject: '数学', title: '高置信', confidence: 0.7,
  } as never)
  const r = lint(g)
  assert.equal(r.warnings.filter(f => f.rule === 'confidence').length, 0)
})

test('rule 13 confidence: 无字段不报', () => {
  const r = lint(loadGraph(fixtures))
  assert.equal(r.warnings.filter(f => f.rule === 'confidence').length, 0)
})

test('rule 13 confidence: 同类超 10 条截断为 …等共 N 条', () => {
  const g = loadGraph(fixtures)
  for (let i = 0; i < 12; i++) {
    g.entities.push({
      id: `concept:数学:存疑${i}`, type: 'Concept', subject: '数学', title: `存疑${i}`, confidence: 0.5,
    } as never)
  }
  const r = lint(g)
  const hits = r.warnings.filter(f => f.rule === 'confidence')
  assert.equal(hits.filter(f => f.ref).length, 10)
  assert.ok(hits.some(f => f.message.includes('等共 12 条')))
})

test('rule 8 sourceRef: 指向不存在的文件报 error', () => {
  const g = loadGraph(fixtures)
  g.entities.push({
    id: 'concept:数学:悬空', type: 'Concept', subject: '数学', title: '悬空',
    sourceRef: 'content/PEP-7-2-English/chapters/C9/sections/S9.md',
  } as never)
  const before = lint(loadGraph(fixtures))
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'sourceRef' && f.ref === 'concept:数学:悬空'))
  assert.equal(r.errors.length, before.errors.length + 1)
})

// fixture 里另有两个概念本就缺 sourceRef（同属 rule 8 的另一分支，仍是 warning），故按消息筛「悬空」这一支
const danglingRefs = (r: LintReport): LintFinding[] =>
  r.errors.filter(f => f.rule === 'sourceRef' && f.message.includes('不存在'))

test('rule 8 sourceRef: 指向存在的文件不报', () => {
  assert.equal(danglingRefs(lint(loadGraph(fixtures))).length, 0)
})

test('rule 8 sourceRef: 带片段锚点时只校验 # 之前的路径', () => {
  const g = loadGraph(fixtures)
  g.entities.push({
    id: 'concept:数学:带锚点', type: 'Concept', subject: '数学', title: '带锚点',
    sourceRef: 'content/PEP-7-2-English/chapters/C1/sections/S1.md#exercise:X-1-S1-E1',
  } as never)
  assert.equal(danglingRefs(lint(g)).length, 0)
})

test('rule 8 sourceRef: 超 10 条截断为 …等共 N 条', () => {
  const g = loadGraph(fixtures)
  for (let i = 0; i < 12; i++) {
    g.entities.push({
      id: `concept:数学:悬空${i}`, type: 'Concept', subject: '数学', title: `悬空${i}`,
      sourceRef: `content/不存在/${i}.md`,
    } as never)
  }
  const hits = danglingRefs(lint(g))
  assert.equal(hits.filter(f => f.ref).length, 10)
  const summary = lint(g).errors.filter(f => f.rule === 'sourceRef' && !f.ref)
  assert.ok(summary.some(f => f.message.includes('等共 12 条')))
})

test('rule 15 extension-provenance: EXT- 虚拟教材走通全部闸门(合法 fixture 已含一本)', () => {
  const g = loadGraph(fixtures)
  const ext = g.entities.find(e => e.id === 'EXT-7-2-EnglishReading')
  assert.ok(ext, 'fixture 应含一本 EXT- 扩展教材')
  assert.equal((ext as { origin?: string }).origin, 'extension')
  assert.equal(lint(g).errors.filter(f => f.rule === 'extension-provenance').length, 0)
})

test('rule 15 extension-provenance: EXT- 前缀却声明 origin: textbook 报错', () => {
  const g = loadGraph(fixtures)
  const ext = g.entities.find(e => e.id === 'EXT-7-2-EnglishReading') as { origin: string; source?: string }
  ext.origin = 'textbook'
  delete ext.source
  assert.ok(lint(g).errors.some(f => f.rule === 'extension-provenance' && f.ref === 'EXT-7-2-EnglishReading'))
})

test('rule 15 extension-provenance: 普通 id 声明 origin: extension 报错', () => {
  const g = loadGraph(fixtures)
  const tb = g.entities.find(e => e.id === 'PEP-7-2-English') as { origin: string; source?: string }
  tb.origin = 'extension'
  tb.source = '某来源'
  assert.ok(lint(g).errors.some(f => f.rule === 'extension-provenance' && f.ref === 'PEP-7-2-English'))
})

test('rule 15 extension-provenance: 扩展知识缺 source 报错', () => {
  const g = loadGraph(fixtures)
  const ext = g.entities.find(e => e.id === 'EXT-7-2-EnglishReading') as { source?: string }
  delete ext.source
  assert.ok(lint(g).errors.some(f => f.rule === 'extension-provenance' && /source/.test(f.message)))
})

test('rule 15 extension-provenance: 原始教材带 source 报错', () => {
  const g = loadGraph(fixtures)
  const tb = g.entities.find(e => e.id === 'PEP-7-2-English') as { source?: string }
  tb.source = '不该有的来源'
  assert.ok(lint(g).errors.some(f => f.rule === 'extension-provenance' && f.ref === 'PEP-7-2-English'))
})

// rule 16 的 subject 枚举校验读的是磁盘上的 front-matter(不是图谱节点),故只能改文件来验;
// 用 try/finally 保证原文恢复,失败也不留脏 fixture。
const BOOK_INDEX = resolve(fixtures, 'content/PEP-7-2-English/index.md')

function withBookSubject(line: string, fn: () => void): void {
  const original = readFileSync(BOOK_INDEX, 'utf8')
  try {
    writeFileSync(BOOK_INDEX, original.replace(/^subject: .*$/m, line))
    fn()
  } finally {
    writeFileSync(BOOK_INDEX, original)
  }
}

test('rule 16 book-frontmatter-schema: 合法 fixture 的 subject 不报错', () => {
  assert.equal(lint(loadGraph(fixtures)).errors.filter(f => /subject/.test(f.message)).length, 0)
})

test('rule 16 book-frontmatter-schema: subject 用英文值报错(学科取值口径统一)', () => {
  withBookSubject('subject: English', () => {
    assert.ok(lint(loadGraph(fixtures)).errors.some(
      f => f.rule === 'book-frontmatter-schema' && /subject/.test(f.message) && /English/.test(f.message)))
  })
})

test('rule 16 book-frontmatter-schema: subject 科学合法(小学科学,裁决 D2)', () => {
  withBookSubject('subject: 科学', () => {
    assert.equal(lint(loadGraph(fixtures)).errors.filter(
      f => f.rule === 'book-frontmatter-schema' && /subject/.test(f.message)).length, 0)
  })
})

test('rule 21 book-index-required: 有 chapters/ 无书级 index.md 报错，补上后消失', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-21-')
  try {
    const book = join(tmp, 'content', '三年级', '上册', '语文', 'PEP-3-1-Chinese')
    mkdirSync(join(book, 'chapters', 'C1'), { recursive: true })
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkBookIndexRequired(g, report)
    assert.deepEqual(report.errors.map(f => [f.rule, f.ref]), [['book-index-required', 'content/三年级/上册/语文/PEP-3-1-Chinese']])
    writeFileSync(join(book, 'index.md'), '---\ntextbookId: PEP-3-1-Chinese\n---\n')
    const again: LintReport = { errors: [], warnings: [] }
    checkBookIndexRequired(g, again)
    assert.equal(again.errors.length, 0)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

// subject 完全缺失轮不到 lint:TextbookSchema 在 loadGraph 就抛了。这条记下这个分工,
// 免得后人看到 lint 里的「(缺失)」分支以为没覆盖,又去补一条永远走不到的用例。
test('subject 缺失在 loadGraph 即抛错,不落到 lint', () => {
  withBookSubject('publisher_placeholder: x', () => {
    assert.throws(() => loadGraph(fixtures), /subject/)
  })
})

// rule 17 的四条：豁免只对「缺失」开口，对「乱填」和章本身一律不开
const CH = 'PEP-7-2-English-C1'
const SEC = 'PEP-7-2-English-C1-S1'
const pick = (g: ReturnType<typeof loadGraph>, id: string): Record<string, unknown> =>
  g.entities.find(e => e.id === id) as unknown as Record<string, unknown>

test('rule 17 pageRange-required: origin: textbook 的 Section 缺 pageRange 报 error', () => {
  const g = loadGraph(fixtures)
  delete pick(g, SEC).pageRange
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'pageRange-required' && f.ref === SEC))
})

test('rule 17 pageRange-required: 所属章声明 bodyHasPageMarkers: false 时，缺 pageRange 的 Section 豁免', () => {
  const g = loadGraph(fixtures)
  delete pick(g, SEC).pageRange
  pick(g, CH).bodyHasPageMarkers = false
  const r = lint(g)
  assert.equal(r.errors.filter(f => f.rule === 'pageRange-required').length, 0)
})

test('rule 17 pageRange-required: 章声明无页标记，节却带着 pageRange，报 error', () => {
  const g = loadGraph(fixtures)
  pick(g, CH).bodyHasPageMarkers = false
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'pageRange-required' && f.ref === SEC))
})

test('rule 17 pageRange-required: bodyHasPageMarkers: false 不豁免章自身的 pageRange', () => {
  const g = loadGraph(fixtures)
  const ch = pick(g, CH)
  ch.bodyHasPageMarkers = false
  delete ch.pageRange
  const r = lint(g)
  assert.ok(r.errors.some(f => f.rule === 'pageRange-required' && f.ref === CH))
})

// rule 19 section-toc-agree: mini fixture + fake 快照，直接调 checkSectionTocAgree
function buildMiniBook(tmp: string, outlineSource: string, sections: Array<{ id: string; title: string }>): void {
  const bookDir = join(tmp, 'content', 'mini-book')
  mkdirSync(bookDir, { recursive: true })
  const fm = [
    '---',
    'textbookId: MINI-1',
    'title: Mini Book',
    'grade: "7"',
    'term: "1"',
    'subject: 数学',
    'publisher: Test',
    'totalPages: 10',
    'origin: textbook',
    `outlineSource: ${outlineSource}`,
    'chapters:',
    '  - id: C1',
    '    title: 第一章',
    '    order: 1',
    '    pageRange: [1, 10]',
    '    sections:',
    ...sections.map(s => `      - id: ${s.id}\n        title: ${s.title}\n        order: 1\n        pageRange: [1, 2]`),
    '---',
    '',
  ].join('\n')
  writeFileSync(join(bookDir, 'index.md'), fm)
}

function buildFakeSnap(tmp: string, entries: Array<{ id: string; title: string }>): string {
  const snap = {
    books: [{
      id: 'MINI-1',
      chapters: [{
        id: 'C1',
        sections: entries,
      }],
    }],
  }
  const p = join(tmp, 'fake_toc.json')
  writeFileSync(p, JSON.stringify(snap))
  return p
}

test('rule 19 section-toc-agree: 标题一致不报（PG 带节序号，宽容比对）', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-19-')
  try {
    buildMiniBook(tmp, 'catalog-toc', [{ id: 'S1', title: '有理数' }])
    const snap = buildFakeSnap(tmp, [{ id: 'MINI-1-C1-S1', title: '1. 有理数' }])
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkSectionTocAgree(g, report, snap)
    assert.equal(report.warnings.filter(f => f.rule === 'section-toc-agree').length, 0)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('rule 19 section-toc-agree: 标题不一致报 warning', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-19-')
  try {
    buildMiniBook(tmp, 'catalog-toc', [{ id: 'S1', title: '无理数' }])
    const snap = buildFakeSnap(tmp, [{ id: 'MINI-1-C1-S1', title: '1. 有理数' }])
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkSectionTocAgree(g, report, snap)
    const hits = report.warnings.filter(f => f.rule === 'section-toc-agree')
    assert.ok(hits.length > 0, '应报至少一条 warning')
    assert.ok(hits[0]!.message.includes('不一致'))
    assert.equal(hits[0]!.ref, 'MINI-1-C1-S1')
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('rule 19 section-toc-agree: 节不在快照中报 warning', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-19-')
  try {
    buildMiniBook(tmp, 'catalog-toc', [{ id: 'S99', title: '神秘节' }])
    const snap = buildFakeSnap(tmp, [])
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkSectionTocAgree(g, report, snap)
    const hits = report.warnings.filter(f => f.rule === 'section-toc-agree')
    assert.ok(hits.some(f => f.message.includes('不在快照中')))
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('rule 19 section-toc-agree: 未标记 outlineSource 的书跳过', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-19-')
  try {
    buildMiniBook(tmp, 'other', [{ id: 'S1', title: '完全不一样的标题' }])
    const snap = buildFakeSnap(tmp, [{ id: 'MINI-1-C1-S1', title: '1.1 有理数' }])
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkSectionTocAgree(g, report, snap)
    assert.equal(report.warnings.filter(f => f.rule === 'section-toc-agree').length, 0)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('rule 19 section-toc-agree: 快照文件不存在时整体跳过', () => {
  const tmp = mkdtempSync('/tmp/kg-lint-19-')
  try {
    buildMiniBook(tmp, 'catalog-toc', [{ id: 'S1', title: '什么都可以' }])
    const g = { rootDir: tmp } as ReturnType<typeof loadGraph>
    const report: LintReport = { errors: [], warnings: [] }
    checkSectionTocAgree(g, report, join(tmp, 'nonexistent.json'))
    assert.equal(report.warnings.filter(f => f.rule === 'section-toc-agree').length, 0)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})

test('rule 22 section-concept-min: 小学无概念节报 error；已覆盖/后记/纯表豁免/初中不报', () => {
  // 直接调规则函数（合成实体字段不全，走完整 lint() 可能触发其他规则噪声）；lint() 接线由 Step 4 真实计数验证
  const g = loadGraph(fixtures)
  const sec = (tb: string, ch: string, s: string, grade: string, subj: string) => ({
    id: `${tb}-${ch}-${s}`, type: 'Section', textbookId: tb, chapterId: `${tb}-${ch}`,
    sourceRef: `content/${grade}/上册/${subj}/${tb}/chapters/${ch}/sections/${s}.md`,
  })
  g.entities.push(
    { id: 'PEP-3-1-Math', type: 'Textbook', grade: '3' } as never,
    { id: 'BSDU-3-1-Math', type: 'Textbook', grade: '3' } as never,
    { id: 'PEP-1-1-Chinese', type: 'Textbook', grade: '1' } as never,
    sec('PEP-3-1-Math', 'C1', 'S1', '三年级', '数学') as never, // 无概念 → 报
    sec('PEP-3-1-Math', 'C1', 'S2', '三年级', '数学') as never, // 有 covered_by → 不报
    sec('BSDU-3-1-Math', 'C12', 'S6', '三年级', '数学') as never, // 后记 → 不报
    sec('PEP-1-1-Chinese', 'C1', 'S1', '一年级', '语文') as never, // 纯表/短页豁免 → 不报
  )
  g.relations.push({ type: 'covered_by', from: 'concept:english:be-verb', to: 'PEP-3-1-Math-C1-S2' })
  const r: LintReport = { errors: [], warnings: [] }
  checkSectionConceptMin(g, r)
  const refs = r.errors.filter(f => f.rule === 'section-concept-min').map(f => f.ref)
  assert.deepEqual(refs, ['PEP-3-1-Math-C1-S1']) // fixture 自带的七年级节不在其中 = 初中不报
})

test('rule 23 covered-by-anchor：节级覆盖率 ≥5 且 ≥50% 才逐节报警，零散只汇总', () => {
  const root = mkdtempSync(join(tmpdir(), 'kg-cba-'))
  const g = loadGraph(fixtures)
  g.rootDir = root
  const write = (rel: string, prose: string): void => {
    const p = join(root, rel)
    mkdirSync(dirname(p), { recursive: true })
    writeFileSync(p, prose)
  }
  // 坏节：正文与 5 个概念全无关（正文 > SECTION_PROSE_MIN）
  write('content/x/chapters/C1/sections/S1.md', '这一节讲的是完全不同的内容，只在讨论天气与季节变化，没有任何知识点名称出现。'.repeat(3))
  // 好节：10 个概念里 9 个能在正文命中，只 1 个锚不上 → 不达 50%
  const goodHits = Array.from({ length: 9 }, (_, i) => `命中词${i}`)
  write('content/x/chapters/C2/sections/S1.md', `${goodHits.join('，')}，本节围绕这些术语展开，正文足够长以通过散文阈值检查。`.repeat(2))

  g.entities.push(
    { id: 'BAD-C1-S1', type: 'Section', sourceRef: 'content/x/chapters/C1/sections/S1.md', title: '坏节' } as never,
    { id: 'GOOD-C2-S1', type: 'Section', sourceRef: 'content/x/chapters/C2/sections/S1.md', title: '好节' } as never,
  )
  for (let i = 0; i < 5; i++) {
    g.entities.push({ id: `concept:bad${i}`, type: 'Concept', title: `坏概念${i}`, subject: '数学' } as never)
    g.relations.push({ type: 'covered_by', from: `concept:bad${i}`, to: 'BAD-C1-S1' })
  }
  for (const h of goodHits) {
    g.entities.push({ id: `concept:${h}`, type: 'Concept', title: h, subject: '数学' } as never)
    g.relations.push({ type: 'covered_by', from: `concept:${h}`, to: 'GOOD-C2-S1' })
  }
  g.entities.push({ id: 'concept:miss', type: 'Concept', title: '好节唯一锚不上', subject: '数学' } as never)
  g.relations.push({ type: 'covered_by', from: 'concept:miss', to: 'GOOD-C2-S1' })

  const r: LintReport = { errors: [], warnings: [] }
  checkCoveredByAnchor(g, r)
  const perSection = r.warnings.filter(f => f.rule === 'covered-by-anchor' && f.ref === 'BAD-C1-S1')
  assert.equal(perSection.length, 1, '坏节应逐节报警')
  assert.ok(perSection[0].message.includes('5 个') || perSection[0].message.includes('100%'))
  assert.equal(r.warnings.filter(f => f.ref === 'GOOD-C2-S1').length, 0, '好节未达 50% 不逐节报警')
  assert.ok(r.warnings.some(f => f.ref === 'covered_by' && f.message.includes('零散')), '零散未锚定应出一条汇总')
  rmSync(root, { recursive: true, force: true })
})

test('rule 25 section-concept-min-junior: 初中真内容节无概念报 warning；结构类按章/节名豁免', () => {
  const root = mkdtempSync(join(tmpdir(), 'kg-junior-'))
  const g = loadGraph(fixtures)
  g.rootDir = root
  const write = (rel: string, prose: string): void => {
    const p = join(root, rel)
    mkdirSync(dirname(p), { recursive: true })
    writeFileSync(p, prose)
  }
  const prose = '本节讲光合作用的原料与产物，正文足够长以通过散文阈值检查。'.repeat(5)
  write('content/七年级/上册/生物/T1/chapters/C1/sections/S1.md', prose)
  write('content/七年级/上册/生物/T1/chapters/C2/sections/S1.md', prose)
  write('content/七年级/上册/生物/T1/chapters/C3/sections/S1.md', prose)

  g.entities.push(
    { id: 'T1', type: 'Textbook', grade: '7' } as never,
    { id: 'T1-C1', type: 'Chapter', title: '第一章 细胞' } as never,
    { id: 'T1-C2', type: 'Chapter', title: '第二章 综合与实践' } as never,
    { id: 'T1-C3', type: 'Chapter', title: '第三章 植物' } as never,
    { id: 'T1-C1-S1', type: 'Section', textbookId: 'T1', chapterId: 'T1-C1', title: '第一节 光合作用', sourceRef: 'content/七年级/上册/生物/T1/chapters/C1/sections/S1.md' } as never,
    { id: 'T1-C2-S1', type: 'Section', textbookId: 'T1', chapterId: 'T1-C2', title: '第一节 项目活动', sourceRef: 'content/七年级/上册/生物/T1/chapters/C2/sections/S1.md' } as never,
    { id: 'T1-C3-S1', type: 'Section', textbookId: 'T1', chapterId: 'T1-C3', title: '第一节 复习题', sourceRef: 'content/七年级/上册/生物/T1/chapters/C3/sections/S1.md' } as never,
  )
  const r: LintReport = { errors: [], warnings: [] }
  checkSectionConceptMinJunior(g, r)
  const refs = r.warnings.filter(f => f.rule === 'section-concept-min-junior').map(f => f.ref)
  assert.deepEqual(refs, ['T1-C1-S1']) // 章名含「综合与实践」、节名含「复习题」均豁免
  assert.equal(r.errors.length, 0, '该规则只报警告，不阻塞构建')
  rmSync(root, { recursive: true, force: true })
})
