import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadGraph } from '../src/load.js'
import { evalPrereq, readPrereqGold } from '../src/eval_prereq.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const g = loadGraph(root)
const gold = readPrereqGold(root)

test('prerequisite 金标完整：300 条、三层各 120/120/60、条目不重复', () => {
  assert.equal(gold.length, 300)
  const byTier: Record<string, number> = {}
  const seen = new Set<string>()
  for (const it of gold) {
    byTier[it.tier] = (byTier[it.tier] ?? 0) + 1
    assert.ok(['correct', 'wrong', 'unsure'].includes(it.verdict), `verdict 非法：${it.fromTitle}`)
    const k = `${it.from}\u0000${it.to}`
    assert.ok(!seen.has(k), `重复条目：${it.fromTitle}←${it.toTitle}`)
    seen.add(k)
  }
  assert.deepEqual(byTier, { audited: 120, promoted: 120, sampled: 60 })
})

test('prerequisite 金标两端都是存在的 Concept', () => {
  const typeById = new Map(g.entities.map(e => [e.id, e.type]))
  for (const it of gold) {
    assert.equal(typeById.get(it.from), 'Concept', `from 不存在：${it.from}`)
    assert.equal(typeById.get(it.to), 'Concept', `to 不存在：${it.to}`)
  }
})

test('prerequisite 金标无回归：判为正确的先修边必须仍在', () => {
  const r = evalPrereq(g, gold)
  assert.deepEqual(
    r.regressions.map(x => `${x.fromTitle}←${x.toTitle}`),
    [],
    '有金标判为正确的先修边被删除或改了类型，需复核后更新金标并注明缘由',
  )
  assert.ok(r.keepRate >= 0.95, `金标保持率过低：${(r.keepRate * 100).toFixed(1)}%`)
})
