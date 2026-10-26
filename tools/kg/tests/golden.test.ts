import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'
import type { EvalCase } from '../src/eval.js'

const KNOWN_FNS = ['concepts', 'prereq', 'demo', 'covered', 'related']
const KNOWN_EXPECT_KEYS = ['required_ids', 'required_keywords', 'min_count', 'must_be_empty']

test('golden.yaml 可读、非空、字段名合法', () => {
  const p = resolve(dirname(fileURLToPath(import.meta.url)), '../eval/golden.yaml')
  const { cases } = parse(readFileSync(p, 'utf8')) as { cases: EvalCase[] }
  assert.ok(cases.length >= 16, `黄金集至少 16 条,实际 ${cases.length}`)
  assert.ok(cases.length <= 20, `黄金集至多 20 条,实际 ${cases.length}`)
  assert.ok(cases.filter(c => c.category === 'honesty').length >= 3, 'honesty 类至少 3 条')
  const seen = new Set<string>()
  for (const c of cases) {
    assert.ok(!seen.has(c.id), `${c.id}: id 重复`)
    seen.add(c.id)
    assert.ok(['accuracy', 'honesty'].includes(c.category), `${c.id}: 未知 category`)
    assert.ok(KNOWN_FNS.includes(c.query.fn), `${c.id}: 未知 fn ${c.query.fn}`)
    assert.ok(c.expect && typeof c.expect === 'object', `${c.id}: 缺 expect`)
    const keys = Object.keys(c.expect)
    assert.ok(keys.length > 0, `${c.id}: expect 为空`)
    for (const k of keys) assert.ok(KNOWN_EXPECT_KEYS.includes(k), `${c.id}: 未知 expect 字段 ${k}(拼写?)`)
    assert.ok(c.note, `${c.id}: 缺 note`)
  }
})
