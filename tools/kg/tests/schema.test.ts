import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EntitySchema, ConceptSchema } from '../src/schema/entities.js'
import { RelationSchema } from '../src/schema/relations.js'
import { loadOntology } from '../src/ontology.js'

test('Concept 实体通过 schema', () => {
  const r = ConceptSchema.safeParse({
    id: 'concept:english:be-verb', type: 'Concept',
    subject: 'english', title: 'be 动词',
    explanation: 'am/is/are', sourceRef: 'content/x.md',
  })
  assert.ok(r.success, JSON.stringify(r.error))
})

test('缺 type 的实体被拒', () => {
  const r = EntitySchema.safeParse({ id: 'x', title: 'y' })
  assert.equal(r.success, false)
})

test('关系 schema 拒绝未知关系类型', () => {
  const r = RelationSchema.safeParse({ type: 'depends_on', from: 'a', to: 'b' })
  assert.equal(r.success, false)
})

test('ontology.yaml 可加载且含 5 种关系', () => {
  const o = loadOntology()
  assert.equal(o.relation_types.length, 5)
  assert.ok(o.entity_types.Concept)
})

test('confidence: 合法值 0~1 通过', () => {
  const r = ConceptSchema.safeParse({
    id: 'concept:数学:测试', type: 'Concept', subject: '数学', title: '测试', confidence: 0.85,
  })
  assert.ok(r.success, JSON.stringify(r.error))
})

test('confidence: 1.5 被拒', () => {
  const r = ConceptSchema.safeParse({
    id: 'concept:数学:测试', type: 'Concept', subject: '数学', title: '测试', confidence: 1.5,
  })
  assert.equal(r.success, false)
})

test('confidence: -0.1 被拒', () => {
  const r = ConceptSchema.safeParse({
    id: 'concept:数学:测试', type: 'Concept', subject: '数学', title: '测试', confidence: -0.1,
  })
  assert.equal(r.success, false)
})

test('EntitySchema 联合拒绝已退役的 ExamModel/Figure（v4）', () => {
  assert.equal(EntitySchema.safeParse({
    id: 'model:数学:t', type: 'ExamModel', subject: '数学', title: 'T', domain: '几何·最值',
  }).success, false)
  assert.equal(EntitySchema.safeParse({
    id: 'fig:x:1', type: 'Figure', figType: 'illustration',
  }).success, false)
})
