import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pageSuffix, formatLine } from '../src/cli_format.js'

type E = Parameters<typeof pageSuffix>[0]
const asE = (o: Record<string, unknown>): E => o as unknown as E
const titleOf = (e: { title?: string; id: string }): string => e.title ?? e.id

test('pageSuffix：有 pageRange 时输出 \\tp.起-止', () => {
  assert.equal(pageSuffix(asE({ id: 'S1', type: 'Section', pageRange: [31, 40] })), '\tp.31-40')
})

test('pageSuffix：无 pageRange 时为空串（不产出空键、不输出 p.）', () => {
  assert.equal(pageSuffix(asE({ id: 'C1', type: 'Concept' })), '')
})

test('pageSuffix：pageRange 形态异常（非数组/长度不对）时为空串，不抛错', () => {
  assert.equal(pageSuffix(asE({ id: 'X', type: 'Section', pageRange: 31 })), '')
  assert.equal(pageSuffix(asE({ id: 'X', type: 'Section', pageRange: [31] })), '')
  assert.equal(pageSuffix(asE({ id: 'X', type: 'Section', pageRange: ['31', '40'] })), '\tp.31-40')
})

test('formatLine：id \\t 标题 \\t [类型] \\t 页码', () => {
  assert.equal(
    formatLine(asE({ id: 'BSDU-7-1-Math-C1-S1', type: 'Section', title: '1 生活中的立体图形', pageRange: [2, 5] }), titleOf),
    'BSDU-7-1-Math-C1-S1\t1 生活中的立体图形\t[Section]\tp.2-5',
  )
})

test('formatLine：无页码时不留尾随制表符', () => {
  assert.equal(
    formatLine(asE({ id: 'concept:数学:有理数', type: 'Concept', title: '有理数' }), titleOf),
    'concept:数学:有理数\t有理数\t[Concept]',
  )
})
