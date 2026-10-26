/**
 * prerequisite 强度（hard/soft）评测：金标 198 条。
 *
 * 只做一件事：金标判定的强度必须仍在数据里（边没被删、强度没被改）。
 * 为什么必须锁：两条便宜规则实测一致率仅 40.9% / 56.6%，所以强度是**逐条判定**出来的，
 * 不是规则派生——一旦被脚本或重构覆盖，等于把逐条成本白扔掉。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import type { LoadedGraph } from './load.js'

export interface StrengthGoldItem { from: string; to: string; fromTitle: string; toTitle: string; subject: string; verdict: 'hard' | 'soft' }

export interface StrengthEvalResult {
  total: number
  keep: number
  regressed: StrengthGoldItem[]
  missing: { from: string; to: string }[]
  keepRate: number
  /** 全库分布（用于观察抖动） */
  distribution: Record<string, number>
}

export function readStrengthGold(root: string): StrengthGoldItem[] {
  return (parse(readFileSync(resolve(root, 'tools/kg/eval/prereq-strength-gold.yaml'), 'utf8')) as { items: StrengthGoldItem[] }).items
}

export function evalStrength(g: LoadedGraph, root: string): StrengthEvalResult {
  const gold = readStrengthGold(root)
  const edge = new Map<string, string>()
  for (const r of g.relations) {
    if (r.type !== 'prerequisite') continue
    edge.set(`${r.from}\u0000${r.to}`, String((r as { strength?: string }).strength ?? ''))
  }
  const res: StrengthEvalResult = { total: gold.length, keep: 0, regressed: [], missing: [], keepRate: 0, distribution: {} }
  for (const it of gold) {
    const v = edge.get(`${it.from}\u0000${it.to}`)
    if (v === undefined) res.missing.push({ from: it.from, to: it.to })
    else if (v === it.verdict) res.keep++
    else res.regressed.push(it)
  }
  for (const v of edge.values()) res.distribution[v || '(空)'] = (res.distribution[v || '(空)'] ?? 0) + 1
  const decided = res.keep + res.regressed.length
  res.keepRate = decided ? res.keep / decided : 0
  return res
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { loadGraph } = await import('./load.js')
  const root = resolve(process.argv[2] ?? '../..')
  const r = evalStrength(loadGraph(root), root)
  console.log(`先修强度金标：${r.total} 条`)
  console.log(`  保持 ${r.keep} ｜ 改判 ${r.regressed.length} ｜ 边缺失 ${r.missing.length}`)
  console.log(`  全库分布：${JSON.stringify(r.distribution)}`)
  console.log(`保持率：${(r.keepRate * 100).toFixed(1)}%`)
  for (const x of r.regressed.slice(0, 5)) console.log(`  △ ${x.fromTitle} ⇐ ${x.toTitle}：金标 ${x.verdict}`)
  for (const x of r.missing.slice(0, 5)) console.log(`  △ 边缺失：${x.from} ⇐ ${x.to}`)
  if (r.regressed.length || r.missing.length) process.exit(1)
}
