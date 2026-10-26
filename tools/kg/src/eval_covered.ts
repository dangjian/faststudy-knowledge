/**
 * covered_by 归属评测：用人工金标检验「概念挂在哪个节/章」这一层语义。
 *
 * 为什么需要它：`lint` 只能校验结构（端点类型、锚点规则、孤儿），回答不了
 * 「这节真的讲了这个概念吗」。2026-10-25 的审计证明，光看 lint 数字会把
 * 假阴性当成缺陷去修（未锚定边里 100% 是规则误报），也会把真错误藏起来。
 *
 * 用法：`pnpm kg:eval:covered`；退出码：金标 correct 的条目消失（回归）→ 1。
 * 测试侧 `tests/eval_covered.test.ts` 复用同一函数做门禁。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import { loadGraph } from './load.js'
import type { LoadedGraph } from './load.js'

export interface CoveredGoldItem {
  id: string
  target: string
  level: 'section' | 'chapter'
  subject: string
  concept: string
  verdict: 'correct' | 'wrong' | 'unsure'
  note?: string
}

export interface CoveredEvalResult {
  total: number
  toSection: number
  toChapter: number
  byLevel: Record<'chapter' | 'section', { keep: number; regressed: number; fixed: number; pending: number; unsure: number }>
  regressions: CoveredGoldItem[]
  pending: CoveredGoldItem[]
  keepRate: number
  /** 章级/节级各自的保持率：两者判读难度不同，合并会互相掩盖 */
  keepRateByLevel: Record<'chapter' | 'section', number>
}

const empty = (): CoveredEvalResult['byLevel']['chapter'] => ({
  keep: 0,
  regressed: 0,
  fixed: 0,
  pending: 0,
  unsure: 0,
})

export function readCoveredGold(root: string): CoveredGoldItem[] {
  const p = resolve(root, 'tools/kg/eval/covered-by-gold.yaml')
  return (parse(readFileSync(p, 'utf8')) as { items: CoveredGoldItem[] }).items
}

/** 逐条对照金标：correct 应仍在 → 缺失即回归；wrong 仍在 → 待修，已挪走 → 已修 */
export function evalCovered(g: LoadedGraph, gold: CoveredGoldItem[]): CoveredEvalResult {
  const covered = new Map<string, Set<string>>()
  let toChapter = 0
  let toSection = 0
  for (const r of g.relations) {
    if (r.type !== 'covered_by') continue
    const from = String(r.from)
    const to = String(r.to)
    const set = covered.get(from) ?? new Set<string>()
    set.add(to)
    covered.set(from, set)
    if (/-C\d+$/.test(to)) toChapter++
    else toSection++
  }

  const byLevel = { chapter: empty(), section: empty() }
  const regressions: CoveredGoldItem[] = []
  const pending: CoveredGoldItem[] = []

  for (const it of gold) {
    const hit = covered.get(it.id)?.has(it.target) ?? false
    const bucket = byLevel[it.level]
    if (it.verdict === 'unsure') { bucket.unsure++; continue }
    if (it.verdict === 'correct') {
      if (hit) bucket.keep++
      else { bucket.regressed++; regressions.push(it) }
    } else if (hit) {
      bucket.pending++
      pending.push(it)
    } else {
      bucket.fixed++
    }
  }

  const keep = byLevel.chapter.keep + byLevel.section.keep
  const decided = keep + byLevel.chapter.regressed + byLevel.section.regressed
  // 章级与节级的判读难度不同（章级只有目录可依、节级有正文），合并成一个保持率会互相掩盖，
  // 故分别给出；门禁与阈值也按档独立（见 tests/eval_covered.test.ts）。
  const rateOf = (k: 'chapter' | 'section'): number => {
    const b = byLevel[k]
    const d = b.keep + b.regressed
    return d ? b.keep / d : 0
  }
  return {
    total: gold.length,
    toSection,
    toChapter,
    byLevel,
    regressions,
    pending,
    keepRate: decided ? keep / decided : 0,
    keepRateByLevel: { chapter: rateOf('chapter'), section: rateOf('section') },
  }
}

const isCli = process.argv[1]?.endsWith('eval_covered.ts') ?? false
if (isCli) {
  const root = resolve(process.argv[2] ?? '../..')
  const gold = readCoveredGold(root)
  const g = loadGraph(root)
  const r = evalCovered(g, gold)
  const pct = (a: number, b: number): string => (b ? `${((a / b) * 100).toFixed(1)}%` : 'n/a')
  const line = (label: string, b: typeof r.byLevel.chapter): string => {
    const decided = b.keep + b.regressed + b.fixed + b.pending
    return `${label}：可判定 ${decided} 条 → 保持 ${b.keep} / 回归 ${b.regressed} / 已修 ${b.fixed} / 待修 ${b.pending} / 无法判定 ${b.unsure}`
  }

  console.log(`covered_by 归属评测（金标 ${r.total} 条，图 ${g.relations.length} 条边）`)
  console.log(`  当前边端点：Section ${r.toSection} / Chapter ${r.toChapter}`)
  console.log(`  ${line('章级', r.byLevel.chapter)}`)
  console.log(`  ${line('节级', r.byLevel.section)}`)
  console.log(`\n金标保持率：${pct(Math.round(r.keepRate * 100), 100)}`
    + `（章级 ${pct(Math.round(r.keepRateByLevel.chapter * 100), 100)} / 节级 ${pct(Math.round(r.keepRateByLevel.section * 100), 100)}）`)

  if (r.regressions.length) {
    console.log(`\n✖ 回归 ${r.regressions.length} 条（金标判为正确，但边已不在）：`)
    for (const x of r.regressions.slice(0, 20)) console.log(`  - ${x.concept} → ${x.target}（${x.note ?? ''}）`)
    process.exit(1)
  }
  if (r.pending.length) {
    console.log(`\n△ 待修 ${r.pending.length} 条（金标判为错误，仍未改）：`)
    for (const x of r.pending.slice(0, 10)) console.log(`  - ${x.concept} → ${x.target}（${x.note ?? ''}）`)
  }
}
