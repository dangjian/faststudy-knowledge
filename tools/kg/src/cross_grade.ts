/**
 * cross_grade.ts — P1.3 跨册先修/包含关系：导出任务 + 校验提议并落盘（本脚本不推导任何边）
 *
 *   tsx src/cross_grade.ts export <root> <textbookId>...
 *       → tools/kg/state/p13/tasks/<tb>.json：本书概念（targets）+ 同学科更早册次的小学概念（candidates）
 *   tsx src/cross_grade.ts apply <root> <textbookId>...
 *       → 读 tools/kg/state/p13/raw/<tb>.json（子 agent 写的提议），逐条校验，通过的追加到
 *         graph/relations/{prerequisite,part_of}.yaml；逐条明细写 tools/kg/state/p13/report/<tb>.json
 *
 * 语义口径 B（docs/ARCHITECTURE.md §6.2）：先判 part_of（from 是 to 的一种/一部分/子话题），
 * 两端互不隶属且有能力依赖才是 prerequisite（from 依赖 to：拿掉 to，from 讲不下去）。
 * 只建跨册边：一端是本书概念，另一端是更早册次的概念。章节顺序不是先修信号（章节链骨架停产（2026-08）），故只校验不推导。
 */
import { resolve } from 'node:path'
import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs'
import { stringify } from 'yaml'
import { loadGraph } from './load.js'
import type { Entity, RelationEdge, ConceptEntity, TextbookEntity } from './schema/types.js'

export type EdgeType = 'prerequisite' | 'part_of'
export interface TaskConcept { id: string; title: string; explanation: string }
export interface Task {
  textbookId: string
  subject: string
  grade: number
  targets: TaskConcept[]
  candidates: (TaskConcept & { textbookId: string })[]
}
export interface Proposed { type: string; from: string; to: string; why?: string }
export type Reason = 'bad-type' | 'self-loop' | 'not-in-task' | 'bad-direction' | 'exists' | 'downstream' | 'cycle'
export interface Verdict { accepted: RelationEdge[]; rejected: { edge: Proposed; reason: Reason }[] }

const STATE = 'tools/kg/state/p13'
const PRIMARY_MAX_GRADE = 6
const BOOK_IN_REF = /^content\/[^/]+\/[^/]+\/[^/]+\/([^/]+)\//

/** 概念所在的书 = covered_by 节所在书 ∪ sourceRef 所在书（初中孤儿的 sourceRef 书段可信、节号不可信，见 P1.2 门 B） */
export function bookConcepts(entities: Entity[], relations: RelationEdge[]): Map<string, Set<string>> {
  const secBook = new Map<string, string>()
  for (const e of entities) if (e.type === 'Section') secBook.set(e.id, e.textbookId)
  const out = new Map<string, Set<string>>()
  const add = (tb: string, id: string) => {
    if (!out.has(tb)) out.set(tb, new Set())
    out.get(tb)!.add(id)
  }
  for (const r of relations) {
    if (r.type !== 'covered_by') continue
    const tb = secBook.get(r.to)
    if (tb) add(tb, r.from)
  }
  for (const e of entities) {
    if (e.type !== 'Concept') continue
    const m = (e.sourceRef ?? '').match(BOOK_IN_REF)
    if (m) add(m[1]!, e.id)
  }
  return out
}

/** 候选 = 同学科、册次更早的小学书的概念（目标是初中书时即全部小学书），去掉目标书自己的概念 */
export function buildTask(entities: Entity[], books: Map<string, Set<string>>, textbookId: string): Task {
  const tbs = new Map<string, TextbookEntity>()
  const concepts = new Map<string, ConceptEntity>()
  for (const e of entities) {
    if (e.type === 'Textbook') tbs.set(e.id, e)
    else if (e.type === 'Concept') concepts.set(e.id, e)
  }
  const tb = tbs.get(textbookId)
  if (!tb) throw new Error(`未知教材 ${textbookId}`)
  const order = (t: TextbookEntity) => Number(t.grade) * 10 + Number(t.term)
  const view = (id: string): TaskConcept => {
    const c = concepts.get(id)
    if (!c) throw new Error(`${textbookId}: 概念 ${id} 不存在`)
    return { id, title: c.title, explanation: c.explanation ?? '' }
  }
  const targetIds = books.get(textbookId) ?? new Set<string>()
  const earlier = [...tbs.values()]
    .filter(t => t.subject === tb.subject && Number(t.grade) <= PRIMARY_MAX_GRADE && order(t) < order(tb))
    .sort((a, b) => order(a) - order(b) || a.id.localeCompare(b.id))
  const candidates = new Map<string, TaskConcept & { textbookId: string }>()
  for (const t of earlier) {
    for (const id of [...(books.get(t.id) ?? [])].sort()) {
      if (!targetIds.has(id) && !candidates.has(id)) candidates.set(id, { ...view(id), textbookId: t.id })
    }
  }
  return { textbookId, subject: tb.subject, grade: Number(tb.grade), targets: [...targetIds].sort().map(view), candidates: [...candidates.values()] }
}

const nameOf = (id: string) => id.split(':').slice(2).join(':')
const subjOf = (id: string) => id.split(':')[1] ?? ''

/** 与 lint rule 14 同口径：同学科且 to 名包含 from 名且更长 = prerequisite 方向反了 */
function isDownstream(from: string, to: string): boolean {
  const fn = nameOf(from)
  const tn = nameOf(to)
  return subjOf(from) === subjOf(to) && fn.length > 0 && tn.includes(fn) && tn.length > fn.length
}

function reachable(adj: Map<string, string[]>, src: string, dst: string): boolean {
  const seen = new Set([src])
  const stack = [src]
  while (stack.length) {
    const n = stack.pop()!
    if (n === dst) return true
    for (const m of adj.get(n) ?? []) if (!seen.has(m)) { seen.add(m); stack.push(m) }
  }
  return false
}

/** 逐条校验，先到先得（后面的条目会看到前面已接受的边，用于查重和查环）。不修改入参 */
export function validate(task: Task, proposed: Proposed[], relations: RelationEdge[]): Verdict {
  const targets = new Set(task.targets.map(c => c.id))
  const cands = new Set(task.candidates.map(c => c.id))
  const adj: Record<EdgeType, Map<string, string[]>> = { prerequisite: new Map(), part_of: new Map() }
  const pairs = new Set<string>() // 已有 prerequisite/part_of 的无序端点对（任一方向、任一类型）
  const link = (t: EdgeType, a: string, b: string) => {
    if (!adj[t].has(a)) adj[t].set(a, [])
    adj[t].get(a)!.push(b)
    pairs.add([a, b].sort().join('|'))
  }
  for (const r of relations) if (r.type === 'prerequisite' || r.type === 'part_of') link(r.type, r.from, r.to)
  const v: Verdict = { accepted: [], rejected: [] }
  for (const p of proposed) {
    const reason = ((): Reason | null => {
      if (p.type !== 'prerequisite' && p.type !== 'part_of') return 'bad-type'
      if (p.from === p.to) return 'self-loop'
      const ok = (targets.has(p.from) && cands.has(p.to)) || (cands.has(p.from) && targets.has(p.to))
      if (!ok) return 'not-in-task'
      if (p.type === 'prerequisite' && !targets.has(p.from)) return 'bad-direction'
      if (pairs.has([p.from, p.to].sort().join('|'))) return 'exists'
      if (p.type === 'prerequisite' && isDownstream(p.from, p.to)) return 'downstream'
      if (reachable(adj[p.type], p.to, p.from)) return 'cycle'
      return null
    })()
    if (reason) { v.rejected.push({ edge: p, reason }); continue }
    const t = p.type as EdgeType
    link(t, p.from, p.to)
    v.accepted.push({ type: t, from: p.from, to: p.to })
  }
  return v
}

/** 只追加新条目、不重写整个文件（part_of.yaml 经 parse/stringify 往返不逐字节相等，整体重写会产生无关 diff） */
function appendEdges(file: string, edges: RelationEdge[]): void {
  if (!edges.length) return
  const cur = readFileSync(file, 'utf8')
  appendFileSync(file, (cur.endsWith('\n') ? '' : '\n') + stringify(edges.map(e => ({ from: e.from, to: e.to }))))
}

function main(): void {
  const [cmd, rootArg, ...tbs] = process.argv.slice(2)
  if ((cmd !== 'export' && cmd !== 'apply') || !rootArg || tbs.length === 0) {
    throw new Error('用法: tsx src/cross_grade.ts <export|apply> <root> <textbookId>...')
  }
  const root = resolve(rootArg)
  const g = loadGraph(root)
  const books = bookConcepts(g.entities, g.relations)
  const dir = (sub: string) => {
    const d = resolve(root, STATE, sub)
    mkdirSync(d, { recursive: true })
    return d
  }
  if (cmd === 'export') {
    for (const tb of tbs) {
      const task = buildTask(g.entities, books, tb)
      writeFileSync(resolve(dir('tasks'), `${tb}.json`), JSON.stringify(task, null, 1))
      console.log(`${tb}: 目标 ${task.targets.length} / 候选 ${task.candidates.length}`)
    }
    return
  }
  const added: Record<EdgeType, RelationEdge[]> = { prerequisite: [], part_of: [] }
  for (const tb of tbs) {
    const taskPath = resolve(root, STATE, 'tasks', `${tb}.json`)
    const rawPath = resolve(root, STATE, 'raw', `${tb}.json`)
    if (!existsSync(taskPath) || !existsSync(rawPath)) throw new Error(`${tb}: 缺 task 或 raw（${taskPath} / ${rawPath}）`)
    const task = JSON.parse(readFileSync(taskPath, 'utf8')) as Task
    const raw = JSON.parse(readFileSync(rawPath, 'utf8')) as { textbookId?: string; edges?: Proposed[] }
    if (raw.textbookId !== tb || !Array.isArray(raw.edges)) throw new Error(`${tb}: raw 格式不对（textbookId 不符或缺 edges 数组）`)
    const v = validate(task, raw.edges, g.relations)
    g.relations.push(...v.accepted)
    for (const e of v.accepted) added[e.type as EdgeType].push(e)
    writeFileSync(resolve(dir('report'), `${tb}.json`), JSON.stringify(v, null, 1))
    const count: Record<string, number> = {}
    for (const r of v.rejected) count[r.reason] = (count[r.reason] ?? 0) + 1
    console.log(`${tb}: 提议 ${raw.edges.length} / 接受 ${v.accepted.length} / 拒绝 ${v.rejected.length} ${JSON.stringify(count)}`)
  }
  for (const t of ['prerequisite', 'part_of'] as const) appendEdges(resolve(root, 'graph/relations', `${t}.yaml`), added[t])
  console.log(`合计 prerequisite +${added.prerequisite.length} / part_of +${added.part_of.length}`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
