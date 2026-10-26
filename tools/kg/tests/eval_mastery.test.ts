import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { readMasteryGold, evalMastery } from '../src/eval_mastery.js'
import type { LoadedGraph } from '../src/load.js'

const ROOT = resolve(import.meta.dirname, '../../..')

test('masteryCriteria 金标完整：30 条、pass/fail 都有、concept 不重复', () => {
  const gold = readMasteryGold(ROOT)
  assert.equal(gold.length, 30)
  assert.equal(new Set(gold.map(g => g.concept)).size, 30)
  assert.equal(gold.filter(g => g.verdict === 'fail').length, 1)
  for (const g of gold) assert.ok(g.text.length > 8 && g.title, `条目异常：${g.concept}`)
})

test('evalMastery：pass 消失记回归，fail 仍在记应删未删', () => {
  const gold = readMasteryGold(ROOT)
  const p = gold.find(g => g.verdict === 'pass')!
  const f = gold.find(g => g.verdict === 'fail')!
  const fake = {
    rootDir: ROOT,
    entities: [
      { id: p.concept, type: 'Concept', title: p.title, masteryCriteria: ['别的标准'] }, // pass 被改写 → regressed
      { id: f.concept, type: 'Concept', title: f.title, masteryCriteria: [f.text] },      // fail 仍在 → lingering
    ],
    relations: [],
  } as unknown as LoadedGraph
  const r = evalMastery(fake, ROOT)
  assert.equal(r.regressed.length, 1)
  assert.equal(r.lingering.length, 1)
  assert.equal(r.missing.length, 28)
})
