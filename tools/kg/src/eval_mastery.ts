/**
 * masteryCriteria 评测：金标 30 条（来自 M2 pilot 的独立盲评）。
 *
 * 金标测两件事：
 *   ① 判 pass 的标准，必须仍**逐字存在于**对应概念的 masteryCriteria 里（防止改写或误删）
 *   ② 判 fail 的标准（易错点是「态度信念」而非可纠正错误），不得再出现在数据里
 *
 * 用法：`pnpm kg:eval:mastery`；有任一违反 → 退出码 1。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import type { LoadedGraph } from './load.js'

export interface MasteryGoldItem {
  concept: string
  title: string
  text: string
  verdict: 'pass' | 'fail'
}

export interface MasteryEvalResult {
  total: number
  /** 判 pass 且仍在数据里 */
  keep: number
  /** 判 pass 但已消失（被改写/删除） */
  regressed: MasteryGoldItem[]
  /** 判 fail 但仍存在（该删没删） */
  lingering: MasteryGoldItem[]
  /** 概念本身不存在 */
  missing: MasteryGoldItem[]
  /** pass 条目的保持率 */
  keepRate: number
}

export function readMasteryGold(root: string): MasteryGoldItem[] {
  const p = resolve(root, 'tools/kg/eval/mastery-gold.yaml')
  return (parse(readFileSync(p, 'utf8')) as { items: MasteryGoldItem[] }).items
}

export function evalMastery(g: LoadedGraph, root: string): MasteryEvalResult {
  const gold = readMasteryGold(root)
  const byId = new Map(g.entities.map(e => [e.id, e]))
  const res: MasteryEvalResult = { total: gold.length, keep: 0, regressed: [], lingering: [], missing: [], keepRate: 0 }

  for (const item of gold) {
    const node = byId.get(item.concept)
    if (!node) {
      res.missing.push(item)
      continue
    }
    const list = (node as { masteryCriteria?: string[] }).masteryCriteria ?? []
    const present = list.includes(item.text)
    if (item.verdict === 'pass') {
      if (present) res.keep++
      else res.regressed.push(item)
    } else if (present) {
      res.lingering.push(item)
    }
  }

  const passTotal = gold.filter(x => x.verdict === 'pass').length
  res.keepRate = passTotal ? res.keep / passTotal : 0
  return res
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { loadGraph } = await import('./load.js')
  const root = resolve(process.argv[2] ?? '../..')
  const g = loadGraph(root)
  const r = evalMastery(g, root)

  console.log(`masteryCriteria 金标：${r.total} 条`)
  console.log(`  保持 ${r.keep} ｜ 回归 ${r.regressed.length} ｜ 应删未删 ${r.lingering.length} ｜ 概念缺失 ${r.missing.length}`)
  console.log(`保持率：${(r.keepRate * 100).toFixed(1)}%`)
  for (const x of r.regressed.slice(0, 5)) console.log(`  △ 回归：${x.title} → ${x.text.slice(0, 40)}`)
  for (const x of r.lingering.slice(0, 5)) console.log(`  △ 应删未删：${x.title} → ${x.text.slice(0, 40)}`)
  if (r.regressed.length || r.lingering.length || r.missing.length) process.exit(1)
}
