import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadGraph } from '../src/load.js'
import { evalCovered, readCoveredGold } from '../src/eval_covered.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const g = loadGraph(root)
const gold = readCoveredGold(root)

test('covered_by 金标文件完整：97 条、verdict 合法、(id,target) 不重复', () => {
  assert.equal(gold.length, 97)
  const seen = new Set<string>()
  for (const it of gold) {
    assert.ok(['correct', 'wrong', 'unsure'].includes(it.verdict), `verdict 非法：${it.concept}`)
    assert.ok(['section', 'chapter'].includes(it.level), `level 非法：${it.concept}`)
    const k = `${it.id}\u0000${it.target}`
    assert.ok(!seen.has(k), `重复条目：${it.concept}→${it.target}`)
    seen.add(k)
  }
})

test('covered_by 金标指向真实存在的实体，且层级匹配', () => {
  const typeById = new Map(g.entities.map(e => [e.id, e.type]))
  for (const it of gold) {
    assert.equal(typeById.get(it.id), 'Concept', `概念不存在：${it.id}`)
    assert.equal(typeById.get(it.target), it.level === 'chapter' ? 'Chapter' : 'Section', `目标层级不符：${it.target}`)
  }
})

test('covered_by 金标无回归：判为正确的归属必须仍在', () => {
  const r = evalCovered(g, gold)
  assert.deepEqual(
    r.regressions.map(x => `${x.concept}→${x.target}`),
    [],
    '有金标判为正确的归属被改动，需要复核后更新金标并注明缘由',
  )
  // 保持率是软门槛：初始 100%，低于 95% 说明改坏了一批归属
  assert.ok(r.keepRate >= 0.95, `金标保持率过低：${(r.keepRate * 100).toFixed(1)}%`)
  // 章级与节级分开设阈：章级只有目录可依、节级有正文，混在一起会掩盖单档退化
  assert.ok(r.keepRateByLevel.chapter >= 0.95, `章级保持率过低：${(r.keepRateByLevel.chapter * 100).toFixed(1)}%`)
  assert.ok(r.keepRateByLevel.section >= 0.95, `节级保持率过低：${(r.keepRateByLevel.section * 100).toFixed(1)}%`)
})
