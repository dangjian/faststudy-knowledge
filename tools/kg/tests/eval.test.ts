import { test } from 'node:test'
import assert from 'node:assert/strict'
import { compareCases, idsOf, judgeCase, latestResultFile, runFn, type EvalCase } from '../src/eval.js'
import type { Entity, RelationEdge } from '../src/schema/types.js'

const nodes = [
  { id: 'concept:数学:数轴', type: 'Concept', subject: '数学', title: '数轴', sourceRef: 'x' },
  { id: 'concept:数学:有理数', type: 'Concept', subject: '数学', title: '有理数', sourceRef: 'x' },
  { id: 'SEC-1', type: 'Section', chapterId: 'CH-1', textbookId: 'TB-1', title: '测试节', sourceRef: 'x' },
  { id: 'word-1', type: 'Word', title: 'axis', sourceRef: 'x' },
] as unknown as Entity[]
const edges = [
  { type: 'covered_by', from: 'concept:数学:数轴', to: 'SEC-1' },
  { type: 'prerequisite', from: 'concept:数学:数轴', to: 'concept:数学:有理数' },
  { type: 'demonstrates', from: 'word-1', to: 'concept:数学:数轴' },
] as unknown as RelationEdge[]

test('idsOf 递归收集 id(数组与嵌套对象)', () => {
  assert.deepEqual(idsOf([{ id: 'a' }, { id: 'b' }]), ['a', 'b'])
  assert.deepEqual(idsOf({ chapter: { id: 'c' }, sections: [{ id: 's1' }], models: [] }), ['c', 's1'])
  assert.deepEqual(idsOf({ chapter: null, sections: [] }), [])
})

test('runFn: concepts / prereq 正常分派,未知 fn 抛错', () => {
  assert.deepEqual(idsOf(runFn(nodes, edges, 'concepts', 'SEC-1')), ['concept:数学:数轴'])
  assert.deepEqual(idsOf(runFn(nodes, edges, 'prereq', 'concept:数学:数轴')), ['concept:数学:有理数'])
  assert.throws(() => runFn(nodes, edges, 'nope', 'x'), /未知 fn/)
})

test('runFn: covered 反查所在节、demo 查演示条目', () => {
  assert.deepEqual(idsOf(runFn(nodes, edges, 'covered', 'concept:数学:数轴')), ['SEC-1'])
  assert.deepEqual(idsOf(runFn(nodes, edges, 'demo', 'concept:数学:数轴')), ['word-1'])
})

function mkCase(over: Partial<EvalCase>): EvalCase {
  return { id: 't', category: 'accuracy', query: { fn: 'concepts', arg: 'SEC-1' }, expect: {}, ...over } as EvalCase
}

test('judgeCase: required_ids 命中通过、缺失失败', () => {
  assert.equal(judgeCase(nodes, edges, mkCase({ expect: { required_ids: ['concept:数学:数轴'] } })).pass, true)
  const r = judgeCase(nodes, edges, mkCase({ expect: { required_ids: ['concept:数学:不存在'] } }))
  assert.equal(r.pass, false)
  assert.match(r.failures[0]!, /required_ids 缺失/)
})

test('judgeCase: must_be_empty 空通过、非空失败并列出命中', () => {
  const empty = mkCase({ query: { fn: 'concepts', arg: 'SEC-99' }, expect: { must_be_empty: true } })
  assert.equal(judgeCase(nodes, edges, empty).pass, true)
  const nonEmpty = judgeCase(nodes, edges, mkCase({ expect: { must_be_empty: true } }))
  assert.equal(nonEmpty.pass, false)
  assert.match(nonEmpty.failures[0]!, /concept:数学:数轴/)
})

test('judgeCase: min_count 与 required_keywords', () => {
  assert.equal(judgeCase(nodes, edges, mkCase({ expect: { min_count: 2 } })).pass, false)
  assert.equal(judgeCase(nodes, edges, mkCase({ expect: { min_count: 1, required_keywords: ['数轴'] } })).pass, true)
  assert.equal(judgeCase(nodes, edges, mkCase({ expect: { required_keywords: ['不存在的词'] } })).pass, false)
})

test('judgeCase: 空 expect 判失败(防字段名拼错假绿)', () => {
  const r = judgeCase(nodes, edges, mkCase({ expect: {} }))
  assert.equal(r.pass, false)
  assert.match(r.failures[0]!, /expect 为空/)
})

test('judgeCase: runFn 抛错转为 fail 而非崩掉整个 run', () => {
  const r = judgeCase(nodes, edges, mkCase({ query: { fn: 'nope', arg: 'x' } }))
  assert.equal(r.pass, false)
  assert.match(r.failures[0]!, /未知 fn/)
})

test('runFn: related 双向查询(出边取 to、入边取 from,去重)', () => {
  const relNodes = [
    { id: 'concept:数学:平方根', type: 'Concept', subject: '数学', title: '平方根', sourceRef: 'x' },
    { id: 'concept:数学:立方根', type: 'Concept', subject: '数学', title: '立方根', sourceRef: 'x' },
    { id: 'concept:数学:无理数', type: 'Concept', subject: '数学', title: '无理数', sourceRef: 'x' },
  ] as unknown as Entity[]
  const relEdges = [
    { type: 'related', from: 'concept:数学:立方根', to: 'concept:数学:平方根' },
    { type: 'related', from: 'concept:数学:无理数', to: 'concept:数学:立方根' },
    { type: 'related', from: 'concept:数学:立方根', to: 'concept:数学:平方根' },
    { type: 'prerequisite', from: 'concept:数学:立方根', to: 'concept:数学:无理数' },
  ] as unknown as RelationEdge[]
  assert.deepEqual(
    idsOf(runFn(relNodes, relEdges, 'related', 'concept:数学:立方根')),
    ['concept:数学:平方根', 'concept:数学:无理数'],
  )
  assert.deepEqual(idsOf(runFn(relNodes, relEdges, 'related', 'concept:数学:不存在')), [])
})

test('compareCases: prev 为 null 时全 added', () => {
  assert.deepEqual(compareCases(null, [{ id: 'a', pass: true }, { id: 'b', pass: false }]), [
    { id: 'a', status: 'added' },
    { id: 'b', status: 'added' },
  ])
})

test('compareCases: up/down/same/added/removed 五态', () => {
  const prev = [
    { id: 'up1', pass: false },
    { id: 'down1', pass: true },
    { id: 'same1', pass: true },
    { id: 'gone1', pass: true },
  ]
  const cur = [
    { id: 'up1', pass: true },
    { id: 'down1', pass: false },
    { id: 'same1', pass: true },
    { id: 'new1', pass: true },
  ]
  assert.deepEqual(compareCases(prev, cur), [
    { id: 'up1', status: 'up' },
    { id: 'down1', status: 'down' },
    { id: 'same1', status: 'same' },
    { id: 'new1', status: 'added' },
    { id: 'gone1', status: 'removed' },
  ])
})

test('latestResultFile: 取字典序最大且非 exclude,空数组返回 null', () => {
  assert.equal(latestResultFile([]), null)
  assert.equal(latestResultFile(['a.json', 'c.json', 'b.json']), 'c.json')
  assert.equal(latestResultFile(['a.json', 'c.json', 'b.json'], 'c.json'), 'b.json')
  assert.equal(latestResultFile(['c.json'], 'c.json'), null)
})
