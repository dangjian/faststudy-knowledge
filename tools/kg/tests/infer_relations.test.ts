import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadGraph } from '../src/load.js'
import { inferRelations } from '../src/infer_relations.js'
import type { RelationEdge } from '../src/schema/types.js'

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures')

// 回归：infer 曾经是覆盖写，会把人工治理（章节链骨架停产（2026-08） 等）加进 related/demonstrates 的边整片抹掉。
test('inferRelations 保留已有的 related 边（写回是并集，不是覆盖）', () => {
  const g = loadGraph(fixtures)
  const manual = { type: 'related', from: 'concept:数学:人工甲', to: 'concept:数学:人工乙' } as RelationEdge
  g.relations.push(manual)

  const { relatedEdges, relatedBase } = inferRelations(g)

  assert.ok(relatedEdges.some(e => e.from === manual.from && e.to === manual.to), '人工边被丢弃了')
  assert.ok(relatedBase >= 1, 'relatedBase 应计入已有边')
  assert.ok(relatedEdges.length >= relatedBase, '输出条数不得少于已有条数')
})

test('inferRelations 保留已有的 demonstrates 边', () => {
  const g = loadGraph(fixtures)
  const manual = { type: 'demonstrates', from: 'word:人工:x', to: 'concept:数学:人工甲' } as RelationEdge
  g.relations.push(manual)

  const { demoEdges, demoBase } = inferRelations(g)

  assert.ok(demoEdges.some(e => e.from === manual.from && e.to === manual.to), '人工边被丢弃了')
  assert.ok(demoEdges.length >= demoBase, '输出条数不得少于已有条数')
})

test('inferRelations 不产出已有 related 边的反向副本（related 无向）', () => {
  const g = loadGraph(fixtures)
  const { relatedEdges } = inferRelations(g)
  const seen = new Set<string>()
  for (const e of relatedEdges) {
    const key = [e.from, e.to].sort().join('\t')
    assert.ok(!seen.has(key), `无向重复: ${e.from} <-> ${e.to}`)
    seen.add(key)
  }
})

test('inferRelations 不产出 prerequisite（章节链骨架停产（2026-08） 已停产）', () => {
  const g = loadGraph(fixtures)
  const { demoEdges, relatedEdges } = inferRelations(g)
  assert.ok(![...demoEdges, ...relatedEdges].some(e => e.type === 'prerequisite'))
})
