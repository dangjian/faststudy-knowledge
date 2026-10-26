import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { readTypeGold, evalType, CONCEPT_TYPE_VALUES } from '../src/eval_type.js'
import type { LoadedGraph } from '../src/load.js'

const ROOT = resolve(import.meta.dirname, '../../..')

test('conceptType 金标完整：98 条、五类取值合法、id 不重复', () => {
  const gold = readTypeGold(ROOT)
  assert.equal(gold.length, 98)
  const ids = new Set(gold.map(g => g.id))
  assert.equal(ids.size, gold.length, '金标 id 必须唯一')
  for (const g of gold) {
    assert.ok(CONCEPT_TYPE_VALUES.includes(g.verdict), `非法类型 ${g.verdict}（${g.title}）`)
    assert.ok(g.title && g.subject, `缺标题或学科：${g.id}`)
  }
  // 分层抽样保证稀有类有样本，不能全落一类
  const byType = new Map<string, number>()
  for (const g of gold) byType.set(g.verdict, (byType.get(g.verdict) ?? 0) + 1)
  assert.ok((byType.get('程序型') ?? 0) >= 15, '程序型样本过少，验收会失真')
})

test('evalType：一致/不一致/缺失/未填 四类分别计数，一致率只算已填', () => {
  const gold = readTypeGold(ROOT)
  const [a, b, c] = gold
  const fake = {
    rootDir: ROOT,
    entities: [
      // 与金标一致
      { id: a!.id, type: 'Concept', title: a!.title, subject: a!.subject, conceptType: a!.verdict },
      // 与金标不一致：取一个与金标不同的值
      { id: b!.id, type: 'Concept', title: b!.title, subject: b!.subject, conceptType: b!.verdict === '概念型' ? '程序型' : '概念型' },
      // 未填
      { id: c!.id, type: 'Concept', title: c!.title, subject: c!.subject },
    ],
    relations: [],
  } as unknown as LoadedGraph

  const r = evalType(fake, ROOT)
  assert.equal(r.total, 98)
  assert.equal(r.keep, 1)
  assert.equal(r.mismatch.length, 1)
  assert.equal(r.missing.length, 95) // 其余 95 条不在这个假图里
  assert.equal(r.unfilled, 1)
  assert.equal(r.agreement, 0.5) // 1 一致 / (1 一致 + 1 不一致)
})

test('evalType：全未填时一致率为 null（不算失败，尚未开始填）', () => {
  const r = evalType({ rootDir: ROOT, entities: [], relations: [] } as unknown as LoadedGraph, ROOT)
  assert.equal(r.unfilled, 0)
  assert.equal(r.missing.length, 98)
  assert.equal(r.agreement, null)
})
