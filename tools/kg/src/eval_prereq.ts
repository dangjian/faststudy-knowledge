/**
 * prerequisite 方向评测：用人工金标检验「学 A 之前是否真的必须先学 B」。
 *
 * lint 只能保证图无环、端点合法、档位已标，回答不了方向对不对——而先修方向是
 * 补救路径的直接输入，错一条就会把学生指去补无关知识点。
 *
 * 用法：`pnpm kg:eval:prereq`；退出码：金标 correct 的先修边消失/改类型（回归）→ 1。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import { loadGraph } from './load.js'
import type { LoadedGraph } from './load.js'

export interface PrereqGoldItem {
  from: string
  to: string
  fromTitle: string
  toTitle: string
  subject: string
  tier: 'audited' | 'promoted' | 'sampled'
  grades?: string
  flags?: string[]
  verdict: 'correct' | 'wrong' | 'unsure'
  note?: string
}

export interface PrereqEvalResult {
  total: number
  byTier: Record<string, { keep: number; regressed: number; fixed: number; pending: number; unsure: number }>
  regressions: PrereqGoldItem[]
  pending: PrereqGoldItem[]
  keepRate: number
}

const empty = (): PrereqEvalResult['byTier'][string] => ({ keep: 0, regressed: 0, fixed: 0, pending: 0, unsure: 0 })

export function readPrereqGold(root: string): PrereqGoldItem[] {
  const p = resolve(root, 'tools/kg/eval/prereq-gold.yaml')
  return (parse(readFileSync(p, 'utf8')) as { items: PrereqGoldItem[] }).items
}

export function evalPrereq(g: LoadedGraph, gold: PrereqGoldItem[]): PrereqEvalResult {
  const prereq = new Set<string>()
  const partOf = new Set<string>()
  for (const r of g.relations) {
    const k = `${r.from}\u0000${r.to}`
    if (r.type === 'prerequisite') prereq.add(k)
    else if (r.type === 'part_of') partOf.add(k)
  }

  const byTier: PrereqEvalResult['byTier'] = {}
  const regressions: PrereqGoldItem[] = []
  const pending: PrereqGoldItem[] = []

  for (const it of gold) {
    const tier = (byTier[it.tier] ??= empty())
    const k = `${it.from}\u0000${it.to}`
    const alive = prereq.has(k)
    if (it.verdict === 'unsure') { tier.unsure++; continue }
    if (it.verdict === 'correct') {
      if (alive) tier.keep++
      else { tier.regressed++; regressions.push(it) }
    } else if (alive) {
      tier.pending++
      pending.push(it)
    } else {
      tier.fixed++ // 已删除或已转 part_of
      void partOf
    }
  }

  const keep = Object.values(byTier).reduce((n, t) => n + t.keep, 0)
  const decided = keep + Object.values(byTier).reduce((n, t) => n + t.regressed, 0)
  return { total: gold.length, byTier, regressions, pending, keepRate: decided ? keep / decided : 0 }
}

const isCli = process.argv[1]?.endsWith('eval_prereq.ts') ?? false
if (isCli) {
  const root = resolve(process.argv[2] ?? '../..')
  const gold = readPrereqGold(root)
  const g = loadGraph(root)
  const r = evalPrereq(g, gold)
  const pct = (a: number, b: number): string => (b ? `${((a / b) * 100).toFixed(1)}%` : 'n/a')

  console.log(`prerequisite 方向评测（金标 ${r.total} 条，图 ${g.relations.length} 条边）`)
  for (const [tier, t] of Object.entries(r.byTier)) {
    const decided = t.keep + t.regressed + t.fixed + t.pending
    console.log(
      `  ${tier.padEnd(9)}：可判定 ${decided} → 保持 ${t.keep} / 回归 ${t.regressed} / 已修 ${t.fixed} / 待修 ${t.pending} / 无法判定 ${t.unsure}`,
    )
  }
  console.log(`\n金标保持率：${pct(Math.round(r.keepRate * 100), 100)}`)

  if (r.regressions.length) {
    console.log(`\n✖ 回归 ${r.regressions.length} 条（金标判为正确，但先修边已不在）：`)
    for (const x of r.regressions.slice(0, 20)) console.log(`  - ${x.fromTitle} ← ${x.toTitle}（${x.note ?? ''}）`)
    process.exit(1)
  }
  if (r.pending.length) {
    console.log(`\n△ 待修 ${r.pending.length} 条（金标判为错误，仍未改）：`)
    for (const x of r.pending.slice(0, 15)) console.log(`  - ${x.fromTitle} ← ${x.toTitle}（${x.note ?? ''}）`)
  }
}
