// eval.ts - 黄金集回归评测(确定性、零 LLM):跑挂的 case 要么暴露查询退化,要么暴露数据变更,都值得被看见
// 结果文件(state/quality/eval/eval-results-*.json)是"运行采样":CI clone 中产生即弃,
// 只有本地提交的才进历史(与 trends 同理);该目录已 gitignore,默认不提交。
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'
import { loadGraph } from './load.js'
import { Query } from './query.js'
import type { Entity, RelationEdge } from './schema/types.js'

export interface EvalCase {
  id: string
  category: 'accuracy' | 'honesty'
  note?: string
  query: { fn: string; arg: string }
  expect: {
    required_ids?: string[]
    required_keywords?: string[]
    // min_count 统计结果中全部 id;精确期望用 required_ids
    min_count?: number
    must_be_empty?: boolean
  }
}

export interface CaseResult { id: string; category: string; pass: boolean; failures: string[] }

// 递归收集结果中所有 id 字段(兼容实体数组与 review-unit 聚合对象)
export function idsOf(result: unknown): string[] {
  const out: string[] = []
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) { for (const x of v) walk(x); return }
    if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>
      if (typeof o.id === 'string') out.push(o.id)
      for (const k of Object.keys(o)) if (k !== 'id') walk(o[k])
    }
  }
  walk(result)
  return out
}

export function runFn(nodes: Entity[], edges: RelationEdge[], fn: string, arg: string): unknown {
  const q = new Query({ nodes, edges })
  switch (fn) {
    case 'concepts': return q.conceptsForSection(arg)
    case 'prereq': return q.prerequisitesOf(arg)
    case 'demo': return q.itemsDemonstrating(arg)
    case 'covered': return q.coveredBySection(arg)
    // related 是无向语义关系:出边取 to ∪ 入边取 from,按 id 去重后映射到节点
    case 'related': {
      const ids = new Set<string>()
      for (const e of edges) {
        if (e.type !== 'related') continue
        if (e.from === arg) ids.add(e.to)
        if (e.to === arg) ids.add(e.from)
      }
      return [...ids].map(id => nodes.find(n => n.id === id)).filter(Boolean)
    }
    default: throw new Error(`未知 fn: ${fn}(golden.yaml 写错,或需先扩展 eval.ts 的 runFn)`)
  }
}

export function judgeCase(nodes: Entity[], edges: RelationEdge[], c: EvalCase): CaseResult {
  const failures: string[] = []
  const known = ['required_ids', 'required_keywords', 'min_count', 'must_be_empty']
  if (!known.some(k => c.expect[k as keyof EvalCase['expect']] !== undefined))
    failures.push('expect 为空(可能是字段名拼写错误)')
  let result: unknown
  try {
    result = runFn(nodes, edges, c.query.fn, c.query.arg)
  } catch (e) {
    return { id: c.id, category: c.category, pass: false, failures: [String(e)] }
  }
  const ids = idsOf(result)
  const e = c.expect
  if (e.must_be_empty && ids.length > 0)
    failures.push(`must_be_empty 但命中 ${ids.length} 个: ${ids.slice(0, 5).join(', ')}`)
  for (const id of e.required_ids ?? [])
    if (!ids.includes(id)) failures.push(`required_ids 缺失: ${id}`)
  if (e.min_count !== undefined && ids.length < e.min_count)
    failures.push(`min_count 不足: 期望 ≥${e.min_count},实际 ${ids.length}`)
  if (e.required_keywords?.length) {
    const text = JSON.stringify(result)
    for (const kw of e.required_keywords)
      if (!text.includes(kw)) failures.push(`required_keywords 缺失: ${kw}`)
  }
  return { id: c.id, category: c.category, pass: failures.length === 0, failures }
}

export type CaseChangeStatus = 'up' | 'down' | 'same' | 'added' | 'removed'
export interface CaseChange { id: string; status: CaseChangeStatus }

// 与上一轮结果逐 case 对比:up=修复,down=退化,removed=上轮有本轮没有(防悄悄删题刷分)
export function compareCases(
  prev: { id: string; pass: boolean }[] | null,
  cur: { id: string; pass: boolean }[],
): CaseChange[] {
  if (!prev) return cur.map(c => ({ id: c.id, status: 'added' as const }))
  const prevById = new Map(prev.map(p => [p.id, p.pass]))
  const curIds = new Set(cur.map(c => c.id))
  const out: CaseChange[] = cur.map(c => {
    const was = prevById.get(c.id)
    if (was === undefined) return { id: c.id, status: 'added' }
    if (was === c.pass) return { id: c.id, status: 'same' }
    return { id: c.id, status: c.pass ? 'up' : 'down' }
  })
  for (const p of prev) if (!curIds.has(p.id)) out.push({ id: p.id, status: 'removed' })
  return out
}

// 字典序最大且 ≠ exclude 的文件名(结果文件名含时间戳,字典序即时间序)
export function latestResultFile(names: string[], exclude?: string): string | null {
  const sorted = names.filter(n => n !== exclude).sort()
  return sorted.length ? sorted[sorted.length - 1]! : null
}

function timestamp(d: Date): string {
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

function main(): void {
  const arg = process.argv.slice(2).find(a => !a.startsWith('-'))
  const root = resolve(arg ?? process.cwd())
  const here = dirname(fileURLToPath(import.meta.url))
  const goldenPath = resolve(here, '../eval/golden.yaml')
  const { cases } = parse(readFileSync(goldenPath, 'utf8')) as { cases: EvalCase[] }
  if (!cases?.length) throw new Error(`黄金集为空: ${goldenPath}`)
  const g = loadGraph(root)
  const nodes = g.entities
  const edges = g.relations
  const results = cases.map(c => judgeCase(nodes, edges, c))
  for (const r of results) {
    if (r.pass) console.log(`✓ [${r.category}] ${r.id}`)
    else console.error(`✗ [${r.category}] ${r.id}`)
    for (const f of r.failures) console.error(`    ${f}`)
  }
  const failed = results.filter(r => !r.pass)
  console.log(`\neval: ${results.length - failed.length}/${results.length} 通过`)

  // 结果落盘 + 与上一轮对比(文件写失败不吞错,直接抛出)
  const outDir = resolve(here, '../state/quality/eval')
  if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true })
  const fileName = `eval-results-${timestamp(new Date())}.json`
  const prevName = latestResultFile(
    readdirSync(outDir).filter(n => n.startsWith('eval-results-') && n.endsWith('.json')),
    fileName,
  )
  let prevCases: { id: string; pass: boolean }[] | null = null
  if (prevName) {
    const prev = JSON.parse(readFileSync(resolve(outDir, prevName), 'utf8')) as {
      cases: { id: string; pass: boolean }[]
    }
    prevCases = prev.cases
  }
  const caseChanges = compareCases(prevCases, results.map(r => ({ id: r.id, pass: r.pass })))
  const regressed = caseChanges.some(c => c.status === 'down' || c.status === 'removed')
  const payload = {
    generatedAt: new Date().toISOString(),
    summary: { total: results.length, passed: results.length - failed.length, failed: failed.length },
    cases: results.map(r => ({ id: r.id, category: r.category, pass: r.pass, failures: r.failures })),
    changes: { comparedTo: prevName, caseChanges, regressed },
  }
  writeFileSync(resolve(outDir, fileName), JSON.stringify(payload, null, 2) + '\n')
  console.log(`结果已写入: state/quality/eval/${fileName}(对比: ${prevName ?? '无上轮记录'})`)
  const notable = caseChanges.filter(c => c.status !== 'same')
  if (!notable.length) console.log('changes: 与上轮一致')
  else {
    for (const c of notable) {
      const line = `changes: [${c.status}] ${c.id}`
      if (c.status === 'down' || c.status === 'removed') console.error(line)
      else console.log(line)
    }
    if (regressed) console.error('changes: regressed=true(存在 down 或 removed)')
  }

  if (failed.length) process.exit(1)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
