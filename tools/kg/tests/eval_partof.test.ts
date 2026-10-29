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

// ── 台账护栏（2026-10-29 独立审计后新增）────────────────────────────────────
// 这三条能挡住本轮发现的全部历史事故：判错边漏降级、判 ok 边被误删、related 反向重复。
// 数据源统一用 yaml 而不是 dist：dist 是构建产物，apply 后要等 kg:build 才更新。
import { readFileSync } from 'node:fs'
import { parse as parseYaml } from 'yaml'

type Edge = { from: string; to: string }

const ledger = JSON.parse(
  readFileSync(resolve(root, 'tools/kg/eval/partof-audit.json'), 'utf8'),
) as Record<string, string>
const partOfEdges = parseYaml(
  readFileSync(resolve(root, 'graph/relations/part_of.yaml'), 'utf8'),
) as Edge[]
const relatedEdges = parseYaml(
  readFileSync(resolve(root, 'graph/relations/related.yaml'), 'utf8'),
) as Edge[]

const edgeKey = (f: string, t: string): string => `${f}|${t}`

test('台账判错(wrong)的边不得留在 part_of', () => {
  const alive = new Set(partOfEdges.map((e) => edgeKey(e.from, e.to)))
  const leaked = Object.entries(ledger)
    .filter(([k, v]) => v.startsWith('wrong') && alive.has(k))
    .map(([k]) => k)
  assert.deepEqual(
    leaked,
    [],
    `有 ${leaked.length} 条判错边仍在 part_of，需跑 partof_audit.py apply`,
  )
})

test('台账判对(ok)的边必须仍在 part_of', () => {
  const alive = new Set(partOfEdges.map((e) => edgeKey(e.from, e.to)))
  const missing = Object.entries(ledger)
    .filter(([k, v]) => v === 'ok' && !alive.has(k))
    .map(([k]) => k)
  assert.deepEqual(
    missing,
    [],
    `有 ${missing.length} 条判为正确的边已消失，可能是误删或节点被删后未同步台账`,
  )
})

test('related 不得有反向重复（无向图按 (a,b) 与 (b,a) 视为同一条）', () => {
  const seen = new Map<string, string>()
  const dups: string[] = []
  for (const e of relatedEdges) {
    const k = [e.from, e.to].sort().join('\u0000')
    if (seen.has(k)) dups.push(`${e.from} ⟷ ${e.to}`)
    else seen.set(k, e.from)
  }
  assert.deepEqual(dups.slice(0, 5), [], `related 有 ${dups.length} 条反向重复边`)
})
