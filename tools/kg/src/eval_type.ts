/**
 * conceptType 评测：用 98 条人工盲判金标检验「教学类型」判得对不对。
 *
 * 为什么需要它：类型直接决定 agent 的教学动作（讲定义 / 演步骤 / 讲证明 / 给情境 / 建模）。
 * 规则法实测在程序型池上只有 48% 精度、全库漏判约 719 条，所以改为 LLM 判定——
 * 但「换了个判定者」不等于「判得对」，必须有独立金标兜着。
 *
 * 用法：`pnpm kg:eval:type`。退出码 1 的两种情况：
 *   ① 金标里的概念在图谱中不存在（数据被误删）
 *   ② 已填值且与金标不一致的比例超过 15%（即一致率 < 85%）
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import type { LoadedGraph } from './load.js'

export type ConceptType = '概念型' | '程序型' | '推理型' | '应用型' | '建模型'
export const CONCEPT_TYPE_VALUES: readonly ConceptType[] = ['概念型', '程序型', '推理型', '应用型', '建模型']

export interface TypeGoldItem {
  id: string
  title: string
  subject: string
  verdict: ConceptType
  note?: string
}

export interface TypeEvalResult {
  total: number
  /** 金标概念在图谱里找不到 */
  missing: TypeGoldItem[]
  /** 已填 conceptType 且与金标一致 */
  keep: number
  /** 已填但与金标不一致 */
  mismatch: { item: TypeGoldItem; actual: string }[]
  /** 尚未填 conceptType */
  unfilled: number
  /** 一致率（仅统计已填部分）；未填时为 null */
  agreement: number | null
}

export function readTypeGold(root: string): TypeGoldItem[] {
  const p = resolve(root, 'tools/kg/eval/concept-type-gold.yaml')
  return (parse(readFileSync(p, 'utf8')) as { items: TypeGoldItem[] }).items
}

export function evalType(g: LoadedGraph, root: string): TypeEvalResult {
  const gold = readTypeGold(root)
  const byId = new Map(g.entities.map(e => [e.id, e]))
  const res: TypeEvalResult = { total: gold.length, missing: [], keep: 0, mismatch: [], unfilled: 0, agreement: null }

  for (const item of gold) {
    const node = byId.get(item.id)
    if (!node) {
      res.missing.push(item)
      continue
    }
    const actual = (node as { conceptType?: string }).conceptType
    if (!actual) {
      res.unfilled++
      continue
    }
    if (actual === item.verdict) res.keep++
    else res.mismatch.push({ item, actual })
  }

  const filled = res.keep + res.mismatch.length
  res.agreement = filled ? res.keep / filled : null
  return res
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { loadGraph } = await import('./load.js')
  const root = resolve(process.argv[2] ?? '../..')
  const g = loadGraph(root)
  const r = evalType(g, root)

  console.log(`conceptType 金标：${r.total} 条`)
  console.log(`  已填 ${r.keep + r.mismatch.length} ｜ 一致 ${r.keep} ｜ 不一致 ${r.mismatch.length} ｜ 未填 ${r.unfilled}`)
  if (r.missing.length) {
    console.log(`\n✗ 金标概念在图谱中不存在 ${r.missing.length} 条：`)
    for (const m of r.missing.slice(0, 10)) console.log(`   - ${m.id}（${m.title}）`)
  }
  if (r.mismatch.length) {
    console.log(`\n△ 与金标不一致 ${r.mismatch.length} 条：`)
    for (const m of r.mismatch.slice(0, 15)) {
      console.log(`   - ${m.item.title}（${m.item.subject}）实际=${m.actual} 金标=${m.item.verdict}`)
      if (m.item.note) console.log(`     依据：${m.item.note}`)
    }
  }
  console.log(`\n一致率：${r.agreement === null ? '（未填任何值，跳过）' : pct(r.agreement)}`)

  let bad = false
  if (r.missing.length) bad = true
  // 门槛 85%：低于它说明判定者（LLM 或规则）不可用
  if (r.agreement !== null && r.agreement < 0.85) bad = true
  if (bad) process.exit(1)
}
