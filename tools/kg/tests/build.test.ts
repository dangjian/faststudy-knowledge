import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build, renderStatsBlock, replaceStatsBlock, shrinkWarning, lastTrendLine, gradeFromSourceRef, deriveGradeRange } from '../src/build.js'
import { loadGraph } from '../src/load.js'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures')

test('build 产出 graph + stats', () => {
  const r = build(loadGraph(fixtures))
  assert.ok(r.graph.nodes.length > 0)
  assert.equal(r.stats.nodes, r.graph.nodes.length)
  assert.equal(r.stats.edges, r.graph.edges.length)
  assert.ok(r.stats.byType.Concept >= 1)
})

test('build 在 lint error 时抛错', () => {
  const g = loadGraph(fixtures)
  g.relations.push({ type: 'prerequisite', from: 'a', to: 'b' })
  assert.throws(() => build(g))
})

test('renderStatsBlock 输出计数快照', () => {
  const block = renderStatsBlock(
    { nodes: 10, edges: 20, byType: { Concept: 7 }, byRelation: { covered_by: 20 } },
    '2026-08-23',
  )
  assert.match(block, /10 nodes, 20 edges/)
  assert.match(block, /Concept \| 7/)
  assert.match(block, /covered_by \| 20/)
  assert.match(block, /2026-08-23/)
})

test('replaceStatsBlock 只替换标记区块,区块外内容不动', () => {
  const src = '# 标题\n<!-- stats:begin -->\n旧内容\n<!-- stats:end -->\n手写尾部'
  const out = replaceStatsBlock(src, '新内容')
  assert.match(out, /新内容/)
  assert.doesNotMatch(out, /旧内容/)
  assert.match(out, /^# 标题/)
  assert.match(out, /手写尾部$/)
})

test('replaceStatsBlock 缺标记时抛错(fail fast)', () => {
  assert.throws(() => replaceStatsBlock('没有标记的文件', 'x'), /stats 标记/)
})

test('shrinkWarning: 无历史(prev=null)不告警', () => {
  assert.equal(shrinkWarning(null, { nodes: 100, edges: 200 }), null)
})

test('shrinkWarning: 缩水未超 10% 不告警', () => {
  assert.equal(shrinkWarning({ nodes: 100, edges: 200 }, { nodes: 90, edges: 180 }), null)
})

test('shrinkWarning: nodes 缩水 11% 触发告警', () => {
  const w = shrinkWarning({ nodes: 100, edges: 200 }, { nodes: 89, edges: 200 })
  assert.ok(w)
  assert.match(w!, /体积骤减/)
  assert.match(w!, /上次 100/)
  assert.match(w!, /本次 89/)
})

test('shrinkWarning: edges 缩水 11% 触发告警', () => {
  const w = shrinkWarning({ nodes: 100, edges: 200 }, { nodes: 100, edges: 178 })
  assert.ok(w)
  assert.match(w!, /上次 200/)
  assert.match(w!, /本次 178/)
})

test('lastTrendLine: 空串返回 null', () => {
  assert.equal(lastTrendLine(''), null)
})

test('lastTrendLine: 多行取最后一个非空行', () => {
  const content = '{"date":"2026-08-01","nodes":10,"edges":20}\n{"date":"2026-08-22","nodes":100,"edges":200}\n'
  assert.deepEqual(lastTrendLine(content), { date: '2026-08-22', nodes: 100, edges: 200 })
})

test('lastTrendLine: 坏行解析失败返回 null 不抛错', () => {
  assert.equal(lastTrendLine('not json at all'), null)
})

test('gradeFromSourceRef 识别一至九年级(小学入图谱 P0.4)', () => {
  assert.equal(gradeFromSourceRef('content/三年级/上册/科学/ES-3-1-Science/chapters/C1/sections/S1.md'), '3')
  assert.equal(gradeFromSourceRef('content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C2/index.md'), '1')
  assert.equal(gradeFromSourceRef('content/七年级/上册/数学/BSDU-7-1-Math/chapters/C1/sections/S1.md'), '7')
  assert.equal(gradeFromSourceRef('graph/entities/concepts/数学.yaml'), null)
  assert.equal(gradeFromSourceRef(undefined), null)
})

test('deriveGradeRange: 章级 covered_by（to=Chapter）也计入年级', () => {
  const maps = {
    textbookGrade: new Map([['BSDU-8-2-Math', '8']]),
    sectionTextbook: new Map<string, string>(),
    sectionChapter: new Map<string, string>(),
    chapterTextbook: new Map([['BSDU-8-2-Math-C1', 'BSDU-8-2-Math']]),
    conceptSections: new Map<string, string[]>(),
    conceptChapters: new Map([['concept:数学:线段垂直平分线的性质定理', ['BSDU-8-2-Math-C1']]]),
  }
  // 只有章级覆盖时，年级照样能推出来（两级化迁移后曾漏算，2026-10-26 修）
  assert.equal(deriveGradeRange('concept:数学:线段垂直平分线的性质定理', maps, undefined), '8')
})

test('deriveGradeRange: covered_by 年级与 sourceRef 年级取并集', () => {
  const maps = {
    textbookGrade: new Map([['BSDU-5-1-Math', '5']]),
    sectionTextbook: new Map([['BSDU-5-1-Math-C2-S1', 'BSDU-5-1-Math']]),
    sectionChapter: new Map<string, string>(),
    conceptSections: new Map([['concept:数学:约分', ['BSDU-5-1-Math-C2-S1']]]),
  }
  const juniorRef = 'content/七年级/上册/数学/BSDU-7-1-Math/chapters/C2/sections/S1.md'
  assert.equal(deriveGradeRange('concept:数学:约分', maps, juniorRef), '5-7')
  assert.equal(deriveGradeRange('concept:数学:约分', maps, undefined), '5')
  assert.equal(
    deriveGradeRange('concept:数学:无覆盖', maps, 'content/八年级/上册/数学/BSDU-8-1-Math/chapters/C1/sections/S1.md'),
    '8',
  )
})
