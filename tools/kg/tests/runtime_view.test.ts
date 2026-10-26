import { test } from 'node:test'
import assert from 'node:assert/strict'
import { projectRuntimeView, runtimeViewMeta } from '../src/runtime_view.js'
import type { Entity, Graph } from '../src/schema/types.js'

function graphOf(nodes: unknown[], edges: unknown[]): Graph {
  return { nodes: nodes as Entity[], edges: edges as Graph['edges'] }
}

test('保留白名单字段,剔除治理字段（standards/gradeRange 已转正进 dist）', () => {
  const out = projectRuntimeView(graphOf([{
    id: 'concept:数学:一元一次方程', type: 'Concept', subject: '数学',
    title: '一元一次方程', explanation: '只含一个未知数…', misconceptions: ['移项不变号'],
    sourceRef: 'content/x.md',
    // 以下为建库期治理字段,不进运行时
    aliases: ['线性方程'], category: '数学概念',
    evidence: ['exercise:E1'], centrality: 0.42, confidence: 0.9,
    // standards / gradeRange 是数据本身,2026-10-26 起进 dist（教研与跨库 join 需要）
    standards: ['S1'], gradeRange: '7',
  }], []))

  assert.deepEqual(out.nodes[0], {
    id: 'concept:数学:一元一次方程', type: 'Concept', sourceRef: 'content/x.md',
    title: '一元一次方程', subject: '数学', explanation: '只含一个未知数…',
    misconceptions: ['移项不变号'], standards: ['S1'], gradeRange: '7',
  })
})

test('undefined 字段不写入,不产出空键', () => {
  const out = projectRuntimeView(graphOf(
    [{ id: 'c1', type: 'Concept', subject: '物理', title: '重力' }], []))
  assert.deepEqual(Object.keys(out.nodes[0]!), ['id', 'type', 'title', 'subject'])
})

test('边保留 strength（教学强度是数据本身）,reason 仍剔除', () => {
  const out = projectRuntimeView(graphOf(
    [
      { id: 'c1', type: 'Concept', subject: '数学', title: 'A' },
      { id: 'c2', type: 'Concept', subject: '数学', title: 'B' },
    ],
    [{ type: 'prerequisite', from: 'c1', to: 'c2', strength: 'hard', reason: '基础' }],
  ))
  // strength 2026-10-26 转正进 dist：消费侧要按 hard/soft 排补救优先级；
  // reason 是建库期治理字段，仍不进运行时。
  assert.deepEqual(out.edges, [{ type: 'prerequisite', from: 'c1', to: 'c2', strength: 'hard' }])
})

test('词汇类整组字段保留(vocabFor 整节点透传依赖它们)', () => {
  const out = projectRuntimeView(graphOf([
    { id: 'w1', type: 'Word', word: 'apple', ipa: '/ˈæpl/', pos: 'n.', meaning: '苹果', sourceRef: 'content/e.md' },
    { id: 'ch1', type: 'Character', char: '春', pinyin: 'chūn', definition: '季节', example: '春天' },
  ], []))
  assert.equal((out.nodes[0] as Record<string, unknown>).ipa, '/ˈæpl/')
  assert.equal((out.nodes[1] as Record<string, unknown>).pinyin, 'chūn')
})

test('未知实体类型必须抛错,而非静默透传或丢弃', () => {
  assert.throws(
    () => projectRuntimeView(graphOf([{ id: 'x1', type: 'Newborn', title: '新类型' }], [])),
    /未知实体类型 Newborn/,
  )
})

test('runtimeViewMeta: v4 后无投影剔除类型', () => {
  const meta = runtimeViewMeta()
  assert.deepEqual(meta.droppedTypes, [])
  assert.ok(meta.fieldsByType.Concept!.includes('misconceptions'))
})
