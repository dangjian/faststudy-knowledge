import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bookConcepts, buildTask, validate, type Task } from '../src/cross_grade.js'
import type { Entity, RelationEdge } from '../src/schema/types.js'

const TB = (id: string, grade: string, term: string, subject = '数学'): Entity =>
  ({ id, type: 'Textbook', title: id, grade, term, subject, publisher: 'X', totalPages: 1 })
const SEC = (id: string, textbookId: string): Entity =>
  ({ id, type: 'Section', chapterId: `${textbookId}-C1`, textbookId, title: id, order: 1, pageRange: [1, 1] })
const C = (title: string, sourceRef?: string, subject = '数学'): Entity =>
  ({ id: `concept:${subject}:${title}`, type: 'Concept', subject, title, explanation: `${title}说明`, sourceRef })
const COV = (title: string, sec: string, subject = '数学'): RelationEdge => ({ type: 'covered_by', from: `concept:${subject}:${title}`, to: sec })
const id = (t: string) => `concept:数学:${t}`

const entities: Entity[] = [
  TB('M-1-1', '1', '1'), TB('M-1-2', '1', '2'), TB('M-2-1', '2', '1'), TB('M-7-1', '7', '1'), TB('C-1-2', '1', '2', '语文'),
  SEC('M-1-1-C1-S1', 'M-1-1'), SEC('M-1-2-C1-S1', 'M-1-2'), SEC('M-2-1-C1-S1', 'M-2-1'), SEC('M-7-1-C1-S1', 'M-7-1'), SEC('C-1-2-C1-S1', 'C-1-2'),
  C('加法'), C('减法'), C('乘法'), C('有理数'),
  C('方程', 'content/七年级/上册/数学/M-7-1/chapters/C9/sections/S9.md'), // 初中孤儿：只有 sourceRef
  C('拼音', undefined, '语文'),
]
const relations: RelationEdge[] = [
  COV('加法', 'M-1-1-C1-S1'), COV('减法', 'M-1-2-C1-S1'), COV('加法', 'M-1-2-C1-S1'),
  COV('乘法', 'M-2-1-C1-S1'), COV('有理数', 'M-7-1-C1-S1'), COV('拼音', 'C-1-2-C1-S1', '语文'),
]

test('bookConcepts = covered_by 所在书 ∪ sourceRef 所在书', () => {
  const b = bookConcepts(entities, relations)
  assert.deepEqual([...b.get('M-1-2')!].sort(), [id('减法'), id('加法')].sort())
  assert.deepEqual([...b.get('M-7-1')!].sort(), [id('方程'), id('有理数')].sort())
})

test('buildTask：候选只取同学科更早册次的小学书，去掉本书自己的概念；初中书取全部小学书', () => {
  const b = bookConcepts(entities, relations)
  const t21 = buildTask(entities, b, 'M-2-1')
  assert.deepEqual(t21.targets.map(c => c.id), [id('乘法')])
  assert.deepEqual(t21.candidates.map(c => [c.id, c.textbookId]), [[id('加法'), 'M-1-1'], [id('减法'), 'M-1-2']])
  const t12 = buildTask(entities, b, 'M-1-2')
  assert.deepEqual(t12.candidates.map(c => c.id), []) // 加法也在本书 → 不进候选
  const t71 = buildTask(entities, b, 'M-7-1')
  assert.deepEqual(t71.candidates.map(c => c.id), [id('加法'), id('减法'), id('乘法')])
  assert.equal(buildTask(entities, b, 'M-1-1').candidates.length, 0)
  assert.throws(() => buildTask(entities, b, 'NOPE'))
})

const task: Task = {
  textbookId: 'M-7-1', subject: '数学', grade: 7,
  targets: [{ id: id('有理数'), title: '有理数', explanation: '' }, { id: id('方程'), title: '方程', explanation: '' }],
  candidates: ['加法', '减法', '乘法', '加法运算'].map(t => ({ id: id(t), title: t, explanation: '', textbookId: 'M-1-1' })),
}

test('validate：合法的 prerequisite 与双向 part_of 接受', () => {
  const v = validate(task, [
    { type: 'prerequisite', from: id('有理数'), to: id('加法') },
    { type: 'part_of', from: id('乘法'), to: id('有理数') },
    { type: 'part_of', from: id('方程'), to: id('减法') },
  ], [])
  assert.equal(v.rejected.length, 0)
  assert.deepEqual(v.accepted.map(e => e.type), ['prerequisite', 'part_of', 'part_of'])
})

test('validate：各拒绝原因', () => {
  const existing: RelationEdge[] = [{ type: 'part_of', from: id('减法'), to: id('有理数') }]
  const v = validate(task, [
    { type: 'related', from: id('有理数'), to: id('加法') },          // bad-type
    { type: 'prerequisite', from: id('有理数'), to: id('有理数') },    // self-loop
    { type: 'prerequisite', from: id('有理数'), to: id('方程') },      // not-in-task（两端都是本书）
    { type: 'prerequisite', from: id('加法'), to: id('有理数') },      // bad-direction（先修的 from 须是本书概念）
    { type: 'prerequisite', from: id('有理数'), to: id('减法') },      // exists（已有反向 part_of）
    { type: 'prerequisite', from: id('方程'), to: id('乘法') },        // 接受
    { type: 'part_of', from: id('乘法'), to: id('方程') },             // exists（本批刚接受过这对）
  ], existing)
  assert.deepEqual(v.rejected.map(r => r.reason), ['bad-type', 'self-loop', 'not-in-task', 'bad-direction', 'exists'].concat(['exists']))
  assert.deepEqual(v.accepted, [{ type: 'prerequisite', from: id('方程'), to: id('乘法') }])
})

test('validate：downstream 与 cycle', () => {
  const t: Task = { ...task, targets: [...task.targets, { id: id('加'), title: '加', explanation: '' }] }
  const v = validate(t, [
    { type: 'prerequisite', from: id('加'), to: id('加法运算') },     // downstream：to 名含 from 名且更长
    { type: 'prerequisite', from: id('有理数'), to: id('加法') },
    { type: 'prerequisite', from: id('方程'), to: id('乘法') },
  ], [{ type: 'prerequisite', from: id('加法'), to: id('方程') }, { type: 'prerequisite', from: id('乘法'), to: id('有理数') }])
  // 有理数→加法：已有 加法→方程，无环，接受；方程→乘法：已有 乘法→有理数→加法→方程，成环
  assert.deepEqual(v.rejected.map(r => r.reason), ['downstream', 'cycle'])
  assert.equal(v.accepted.length, 1)
})
