import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadGraph } from '../src/load.js'
import { evalPartOf, readPartOfGold } from '../src/eval_partof.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const g = loadGraph(root)
const gold = readPartOfGold(root)

test('part_of 金标完整：500 条、三层各 200/200/100、条目不重复', () => {
  assert.equal(gold.length, 500)
  const byStratum: Record<string, number> = {}
  const seen = new Set<string>()
  for (const it of gold) {
    byStratum[it.stratum] = (byStratum[it.stratum] ?? 0) + 1
    assert.ok(['correct', 'wrong', 'unsure'].includes(it.verdict), `verdict 非法：${it.fromTitle}`)
    const k = `${it.from}\u0000${it.to}`
    assert.ok(!seen.has(k), `重复条目：${it.fromTitle}→${it.toTitle}`)
    seen.add(k)
  }
  assert.deepEqual(byStratum, { A: 200, B: 200, C: 100 })
})

test('part_of 金标两端都是存在的 Concept', () => {
  const typeById = new Map(g.entities.map(e => [e.id, e.type]))
  for (const it of gold) {
    assert.equal(typeById.get(it.from), 'Concept', `from 不存在：${it.from}`)
    assert.equal(typeById.get(it.to), 'Concept', `to 不存在：${it.to}`)
  }
})

test('part_of 金标无回归：判为正确的层级边必须仍在', () => {
  const r = evalPartOf(g, gold)
  assert.deepEqual(
    r.regressions.map(x => `${x.fromTitle}→${x.toTitle}`),
    [],
    '有金标判为正确的 part_of 被删除或改了端点，需复核后更新金标并注明缘由',
  )
  assert.ok(r.keepRate >= 0.95, `金标保持率过低：${(r.keepRate * 100).toFixed(1)}%`)
})
