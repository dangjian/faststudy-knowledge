/**
 * part_of 层级评测：用人工金标检验「A 属于 B」是否成立。
 *
 * lint 只能保证端点类型合法、无环；它回答不了「A 到底是不是 B 的一种/一部分」。
 * 这是 5,163 条关系里唯一没有语义验证的一块，而它直接决定「上位知识」能否被正确推荐。
 *
 * 用法：`pnpm kg:eval:partof`；退出码：金标 correct 的边消失/改类型 → 1。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import type { LoadedGraph } from './load.js'

export interface PartOfGoldItem {
  from: string
  to: string
  fromTitle: string
  toTitle: string
  subject: string
  stratum: 'A' | 'B' | 'C'
  grades?: string
  verdict: 'correct' | 'wrong' | 'unsure'
  note?: string
}

export interface PartOfEvalResult {
  total: number
  byStratum: Record<string, { keep: number; regressed: number; fixed: number; pending: number; unsure: number }>
  regressions: PartOfGoldItem[]
  pending: PartOfGoldItem[]
  keepRate: number
}

const empty = (): PartOfEvalResult['byStratum'][string] => ({ keep: 0, regressed: 0, fixed: 0, pending: 0, unsure: 0 })

export function readPartOfGold(root: string): PartOfGoldItem[] {
  const p = resolve(root, 'tools/kg/eval/part-of-gold.yaml')
  return (parse(readFileSync(p, 'utf8')) as { items: PartOfGoldItem[] }).items
}

export function evalPartOf(g: LoadedGraph, gold: PartOfGoldItem[]): PartOfEvalResult {
  const partOf = new Set<string>()
  for (const r of g.relations) if (r.type === 'part_of') partOf.add(`${r.from}\u0000${r.to}`)

  const byStratum: PartOfEvalResult['byStratum'] = {}
  const regressions: PartOfGoldItem[] = []
  const pending: PartOfGoldItem[] = []

  for (const it of gold) {
    const bucket = (byStratum[it.stratum] ??= empty())
    const alive = partOf.has(`${it.from}\u0000${it.to}`)
    if (it.verdict === 'unsure') { bucket.unsure++; continue }
    if (it.verdict === 'correct') {
      if (alive) bucket.keep++
      else { bucket.regressed++; regressions.push(it) }
    } else if (alive) {
      bucket.pending++
      pending.push(it)
    } else {
      bucket.fixed++
    }
  }

  const keep = Object.values(byStratum).reduce((n, t) => n + t.keep, 0)
  const regressed = Object.values(byStratum).reduce((n, t) => n + t.regressed, 0)
  const decided = keep + regressed
  return { total: gold.length, byStratum, regressions, pending, keepRate: decided ? keep / decided : 0 }
}

const isCli = process.argv[1]?.endsWith('eval_partof.ts') ?? false
if (isCli) {
  const root = resolve(process.argv[2] ?? '../..')
  const { loadGraph } = await import('./load.js')
  const gold = readPartOfGold(root)
  const g = loadGraph(root)
  const r = evalPartOf(g, gold)
  const pct = (a: number, b: number): string => (b ? `${((a / b) * 100).toFixed(1)}%` : 'n/a')
  const labels: Record<string, string> = { A: '标题含容', B: '跨章', C: '同章' }

  console.log(`part_of 层级评测（金标 ${r.total} 条）`)
  for (const [k, t] of Object.entries(r.byStratum)) {
    console.log(
      `  ${labels[k] ?? k}：可判定 ${t.keep + t.regressed + t.fixed + t.pending} → 保持 ${t.keep} / 回归 ${t.regressed} / 已修 ${t.fixed} / 待修 ${t.pending} / 无法判定 ${t.unsure}`,
    )
  }
  console.log(`\n金标保持率：${pct(Math.round(r.keepRate * 100), 100)}`)

  if (r.regressions.length) {
    console.log(`\n✖ 回归 ${r.regressions.length} 条（金标判为正确，但边已不在）：`)
    for (const x of r.regressions.slice(0, 20)) console.log(`  - ${x.fromTitle} → ${x.toTitle}（${x.note ?? ''}）`)
    process.exit(1)
  }
  if (r.pending.length) {
    console.log(`\n△ 待修 ${r.pending.length} 条（金标判为错误，仍未改）：`)
    for (const x of r.pending.slice(0, 15)) console.log(`  - ${x.fromTitle} → ${x.toTitle}（${x.note ?? ''}）`)
  }
}
