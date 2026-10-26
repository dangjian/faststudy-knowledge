import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { readStrengthGold, evalStrength } from '../src/eval_strength.js'
import type { LoadedGraph } from '../src/load.js'

const ROOT = resolve(import.meta.dirname, '../../..')

test('先修强度金标完整：198 条、hard/soft 都有、边不重复', () => {
  const gold = readStrengthGold(ROOT)
  assert.equal(gold.length, 198)
  assert.equal(new Set(gold.map(g => `${g.from}\u0000${g.to}`)).size, 198)
  assert.ok(gold.filter(g => g.verdict === 'hard').length > 100)
  assert.ok(gold.filter(g => g.verdict === 'soft').length > 40)
})

test('evalStrength：强度被改判记 regressed，边消失记 missing', () => {
  const gold = readStrengthGold(ROOT)
  const a = gold.find(g => g.verdict === 'hard')!
  const b = gold.find(g => g.verdict === 'soft')!
  const fake = {
    rootDir: ROOT,
    entities: [],
    relations: [
      { type: 'prerequisite', from: a.from, to: a.to, strength: 'soft' }, // 被改判
      // b 的边缺失
    ],
  } as unknown as LoadedGraph
  const r = evalStrength(fake, ROOT)
  assert.equal(r.regressed.length, 1)
  assert.equal(r.missing.length, 197)
})
