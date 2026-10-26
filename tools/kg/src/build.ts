import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { parse } from 'yaml'
import { loadGraph } from './load.js'
import { lint, loadSuspendedEdges } from './lint.js'
import { projectRuntimeView, runtimeViewMeta } from './runtime_view.js'
import type { Graph, Entity, RelationEdge } from './schema/types.js'

export interface BuildResult {
  graph: Graph
  stats: { nodes: number; edges: number; byType: Record<string, number>; byRelation: Record<string, number> }
  standards: { conceptsWithStandards: number; alignedChapters: number; totalStandardIds: number }
}

const BUILD_VERSION = '1.0.0'

// 从 chapter-standards.yaml 加载章节→标准对齐
function loadChapterStandards(rootDir: string): { chapterMap: Map<string, string[]>; standardsRegistry: Map<string, { subject: string; edition: string; theme: string }> } {
  const chapterMap = new Map<string, string[]>()
  const standardsRegistry = new Map<string, { subject: string; edition: string; theme: string }>()
  try {
    const chRaw = parse(readFileSync(resolve(rootDir, 'graph/chapter-standards.yaml'), 'utf8')) as Array<{ chapterId: string; standards: string[] }>
    for (const row of chRaw ?? []) {
      if (row.chapterId && Array.isArray(row.standards)) chapterMap.set(row.chapterId, row.standards)
    }
  } catch { /* 可选文件缺失时降级 */ }
  try {
    const stdRaw = parse(readFileSync(resolve(rootDir, 'graph/curriculum-standards.yaml'), 'utf8')) as Array<{ id: string; subject: string; edition: string; theme: string }>
    for (const s of stdRaw ?? []) {
      if (s.id) standardsRegistry.set(s.id, { subject: s.subject, edition: s.edition, theme: s.theme })
    }
  } catch { /* 同上 */ }
  return { chapterMap, standardsRegistry }
}

// 从 textbook id（如 BSDU-8-2-Math）解析年级数字
function gradeFromTextbookId(id: string): string | null {
  const m = id.match(/^\s*[A-Za-z]+-(\d+)-/)
  return m ? m[1] : null
}

// 从 sourceRef 路径（content/一年级～九年级/... 或 content/.../BSDU-8-2-Math/...）解析年级
const ZH_GRADE: Record<string, string> = { '一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9' }
export function gradeFromSourceRef(sr: string | undefined): string | null {
  if (!sr) return null
  const zh = sr.match(/content\/([一二三四五六七八九])年级/)
  if (zh) return ZH_GRADE[zh[1]!]
  const tb = sr.match(/content\/[一二三四五六七八九]年级\/(?:上册|下册)\/[^/]+\/([^/]+)\/chapters/)
  if (tb) return gradeFromTextbookId(tb[1]!)
  return null
}

function buildGradeMaps(g: ReturnType<typeof loadGraph>) {
  const textbookGrade = new Map<string, string>()
  const sectionTextbook = new Map<string, string>()
  const sectionChapter = new Map<string, string>()
  const chapterTextbook = new Map<string, string>()
  for (const e of g.entities) {
    if (e.type === 'Textbook') textbookGrade.set(e.id, (e as { grade: string }).grade)
    if (e.type === 'Chapter') {
      const c = e as { id: string; textbookId?: string }
      if (c.textbookId) chapterTextbook.set(c.id, c.textbookId)
    }
    if (e.type === 'Section') {
      const s = e as { id: string; chapterId: string; textbookId: string }
      sectionTextbook.set(s.id, s.textbookId)
      sectionChapter.set(s.id, s.chapterId)
    }
  }
  // covered_by 两级（2026-10-26）：to=Section 归节，to=Chapter 归章。
  // 章级边必须一并映射，否则「只有章级覆盖」的 1,293 个概念会丢掉年级与课标——
  // 这是两级化迁移后遗留的漏算（实测漏掉 1,269 个概念的 standards）。
  const conceptSections = new Map<string, string[]>()
  const conceptChapters = new Map<string, string[]>()
  for (const r of g.relations) {
    if (r.type !== 'covered_by') continue
    const to = r.to
    if (sectionChapter.has(to)) {
      const arr = conceptSections.get(r.from) ?? []
      arr.push(to)
      conceptSections.set(r.from, arr)
    } else if (chapterTextbook.has(to)) {
      const arr = conceptChapters.get(r.from) ?? []
      arr.push(to)
      conceptChapters.set(r.from, arr)
    }
  }
  return { textbookGrade, sectionTextbook, sectionChapter, chapterTextbook, conceptSections, conceptChapters }
}

// 概念学段区间：聚合该概念被覆盖的所有 section 所属教材的年级
export function deriveGradeRange(conceptId: string, maps: ReturnType<typeof buildGradeMaps>, sr?: string): string | undefined {
  const grades = new Set<string>()
  for (const secId of maps.conceptSections.get(conceptId) ?? []) {
    const tb = maps.sectionTextbook.get(secId)
    const g = tb ? (maps.textbookGrade.get(tb) ?? gradeFromTextbookId(tb)) : null
    if (g) grades.add(g)
  }
  for (const chId of maps.conceptChapters?.get(conceptId) ?? []) {
    const tb = maps.chapterTextbook.get(chId)
    const g = tb ? (maps.textbookGrade.get(tb) ?? gradeFromTextbookId(tb)) : null
    if (g) grades.add(g)
  }
  // sourceRef = 概念首次录入出处，本身也是一次真实出现，与 covered_by 年级取并集：
  // D1 跨学段合并后，初中概念若只挂上小学 covered_by，不能把初中出处年级丢掉
  const srGrade = gradeFromSourceRef(sr)
  if (srGrade) grades.add(srGrade)
  if (grades.size === 0) return undefined
  const sorted = [...grades].sort((a, b) => Number(a) - Number(b))
  return sorted.length === 1 ? sorted[0]! : `${sorted[0]}-${sorted[sorted.length - 1]!}`
}

// 先修 DAG 上的 PageRank 重要性（0-1，越高越基础）
function computeCentrality(
  conceptIds: Set<string>,
  prereqEdges: { from: string; to: string }[],
): Map<string, number> {
  const nodes = [...conceptIds]
  const N = nodes.length
  if (N === 0) return new Map()
  // 链接方向：prerequisite(to) -> dependent(from)，使基础概念积累权重
  const out = new Map<string, string[]>()
  for (const n of nodes) out.set(n, [])
  for (const e of prereqEdges) {
    if (out.has(e.to) && conceptIds.has(e.from)) out.get(e.to)!.push(e.from)
  }
  const dangling = nodes.filter(n => out.get(n)!.length === 0)
  let rank = new Map<string, number>()
  for (const n of nodes) rank.set(n, 1 / N)
  const d = 0.85
  for (let i = 0; i < 40; i++) {
    const next = new Map<string, number>()
    for (const n of nodes) next.set(n, (1 - d) / N)
    for (const n of nodes) {
      const od = out.get(n)!.length
      if (od === 0) continue
      const contrib = (d * rank.get(n)!) / od
      for (const m of out.get(n)!) next.set(m, next.get(m)! + contrib)
    }
    let danglingMass = 0
    for (const n of dangling) danglingMass += d * rank.get(n)!
    for (const n of nodes) next.set(n, next.get(n)! + danglingMass / N)
    rank = next
  }
  let max = 0
  for (const n of nodes) max = Math.max(max, rank.get(n)!)
  const result = new Map<string, number>()
  for (const n of nodes) result.set(n, max > 0 ? rank.get(n)! / max : 0)
  return result
}

export function build(g: ReturnType<typeof loadGraph>, opts?: { rootDir?: string; chapterStandards?: Map<string, string[]> }): BuildResult {
  const rootDir = opts?.rootDir ?? ''
  const report = lint(g, loadSuspendedEdges(rootDir))
  if (report.errors.length > 0) {
    throw new Error(`lint 失败，${report.errors.length} 个 error，先修复再 build`)
  }

  const chapterMap = opts?.chapterStandards ?? (rootDir
    ? loadChapterStandards(rootDir).chapterMap
    : new Map<string, string[]>())

  const maps = buildGradeMaps(g)

  const prereqEdges: { from: string; to: string }[] = []
  for (const r of g.relations) {
    if (r.type === 'prerequisite') prereqEdges.push({ from: r.from, to: r.to })
  }

  const conceptIds = new Set<string>()
  for (const e of g.entities) if (e.type === 'Concept') conceptIds.add(e.id)
  const centrality = computeCentrality(conceptIds, prereqEdges)

  // 装饰 Concept 节点（dist 增强字段）
  let conceptsWithStandards = 0
  for (const e of g.entities as Entity[]) {
    if (e.type !== 'Concept') continue
    const c = e as Extract<Entity, { type: 'Concept' }>
    const gradeRange = deriveGradeRange(c.id, maps, c.sourceRef)
    if (gradeRange) (c as Record<string, unknown>).gradeRange = gradeRange
    const cen = centrality.get(c.id)
    if (cen !== undefined) (c as Record<string, unknown>).centrality = Number(cen.toFixed(4))
    // 课标对齐：经 covered_by → Section → Chapter 汇聚 chapter 的 standards
    const stdSet = new Set<string>()
    for (const secId of maps.conceptSections.get(c.id) ?? []) {
      const chId = maps.sectionChapter.get(secId)
      if (!chId) continue
      for (const s of chapterMap.get(chId) ?? []) stdSet.add(s)
    }
    for (const chId of maps.conceptChapters?.get(c.id) ?? []) {
      for (const s of chapterMap.get(chId) ?? []) stdSet.add(s)
    }
    if (stdSet.size) {
      (c as Record<string, unknown>).standards = [...stdSet]
      conceptsWithStandards++
    }
  }

  // 装饰 prerequisite 边：缺失 strength 默认 hard
  const edges = g.relations.map((r): RelationEdge => {
    if (r.type === 'prerequisite' && !r.strength) return { ...r, strength: 'hard' }
    return r
  })

  const graph: Graph = { nodes: g.entities, edges }
  const byType: Record<string, number> = {}
  for (const e of g.entities) byType[e.type] = (byType[e.type] ?? 0) + 1
  const byRelation: Record<string, number> = {}
  for (const r of edges) byRelation[r.type] = (byRelation[r.type] ?? 0) + 1
  return {
    graph,
    stats: { nodes: g.entities.length, edges: edges.length, byType, byRelation },
    standards: {
      conceptsWithStandards,
      alignedChapters: chapterMap.size,
      totalStandardIds: new Set<string>(
        g.entities.flatMap((e) => (e.type === 'Concept' ? ((e as Record<string, unknown>).standards as string[] | undefined) ?? [] : [])),
      ).size,
    },
  }
}

// graph/index.md 计数快照区块(agent 入口文档;区块外内容为手写,build 只动区块内)
const STATS_BEGIN = '<!-- stats:begin -->'
const STATS_END = '<!-- stats:end -->'

export function renderStatsBlock(stats: BuildResult['stats'], date: string): string {
  const typeRows = Object.entries(stats.byType).map(([t, n]) => `| ${t} | ${n} |`).join('\n')
  const relRows = Object.entries(stats.byRelation).map(([t, n]) => `| ${t} | ${n} |`).join('\n')
  return [
    `> 最后更新: ${date} | 分层 v4 | ${stats.nodes} nodes, ${stats.edges} edges`,
    '',
    '| 实体类型 | 数量 |', '|---|---|', typeRows,
    '',
    '| 关系类型 | 数量 |', '|---|---|', relRows,
  ].join('\n')
}

export function replaceStatsBlock(src: string, block: string): string {
  const b = src.indexOf(STATS_BEGIN)
  const e = src.indexOf(STATS_END)
  if (b < 0 || e < 0 || e < b) throw new Error('graph/index.md 缺少 stats 标记区块(<!-- stats:begin/end -->)')
  return src.slice(0, b + STATS_BEGIN.length) + '\n' + block + '\n' + src.slice(e)
}

// 体积哨兵：与上一次 trends 记录比较，nodes 或 edges 缩水 >10% 时给出告警文案（不阻断）
export function shrinkWarning(
  prev: { nodes: number; edges: number } | null,
  cur: { nodes: number; edges: number },
): string | null {
  if (!prev) return null
  const shrunk = (p: number, c: number) => p > 0 && (p - c) / p > 0.1
  if (shrunk(prev.nodes, cur.nodes) || shrunk(prev.edges, cur.edges)) {
    return `WARNING: 图谱体积骤减 nodes(上次 ${prev.nodes},本次 ${cur.nodes}) edges(上次 ${prev.edges},本次 ${cur.edges})——检查是否误删`
  }
  return null
}

// 解析 trends.jsonl 文本最后一个非空行；空/解析失败视为无历史
export function lastTrendLine(content: string): { date: string; nodes: number; edges: number } | null {
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean)
  const last = lines[lines.length - 1]
  if (!last) return null
  try {
    const o = JSON.parse(last) as { date?: string; nodes?: number; edges?: number }
    if (typeof o.date !== 'string' || typeof o.nodes !== 'number' || typeof o.edges !== 'number') return null
    return { date: o.date, nodes: o.nodes, edges: o.edges }
  } catch {
    return null
  }
}

function sha256Of(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

function main(): void {
  const arg = process.argv.slice(2).find(a => !a.startsWith('-'))
  const root = resolve(arg ?? process.cwd())
  const distDir = resolve(root, 'dist')
  // 仓库根 .env（私有侧可选配置：KG_PAGE_IMAGE_BASE_URL 等；不入仓，已设环境变量优先）
  const envFile = resolve(root, '.env')
  if (existsSync(envFile)) {
    for (const line of readFileSync(envFile, 'utf-8').split('\n')) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$/)
      if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].trim().replace(/^["']|["']$/g, '')
    }
  }
  const result = build(loadGraph(root), { rootDir: root })
  mkdirSync(distDir, { recursive: true })

  const graphPath = resolve(distDir, 'graph.json')
  const statsPath = resolve(distDir, 'stats.json')
  // graph.json 是后端运行时视图,按白名单投影且不缩进(见 runtime_view.ts)；
  // stats/manifest 是给人读的,保持缩进
  const runtime = projectRuntimeView(result.graph)
  writeFileSync(graphPath, JSON.stringify(runtime))
  writeFileSync(statsPath, JSON.stringify(result.stats, null, 2))

  // manifest：计数 + 各产物 SHA-256 校验和（强化对外分发可信度）
  const manifest = {
    version: BUILD_VERSION,
    generatedAt: new Date().toISOString(),
    contract: {
      graphJson: '{ nodes: Entity[], edges: RelationEdge[] } —— 运行时视图,已按 runtimeView 投影',
      statsJson: '{ nodes, edges, byType, byRelation } —— 建库口径,投影前',
    },
    // counts 为源图计数(投影前);graph.json 的实际计数见 runtimeView.counts
    counts: {
      nodes: result.stats.nodes,
      edges: result.stats.edges,
      byType: result.stats.byType,
      byRelation: result.stats.byRelation,
    },
    // 投影口径必须在此可见:字段没进白名单只会表现为「agent 拿不到数据」这类难查的症状
    runtimeView: {
      counts: { nodes: runtime.nodes.length, edges: runtime.edges.length },
      ...runtimeViewMeta(),
    },
    // build 派生的字段。⚠️ 其中未列入 runtimeView.fieldsByType 的不进 graph.json,
    // 需要它们请走 loadGraph 读 YAML 源
    derivedFields: {
      concept: ['gradeRange', 'standards', 'centrality'],
      prerequisiteEdge: ['strength (default: hard)', 'reason'],
    },
    files: {
      'graph.json': { sha256: sha256Of(graphPath), bytes: readFileSync(graphPath).length },
      'stats.json': { sha256: sha256Of(statsPath), bytes: readFileSync(statsPath).length },
    },
  }
  const manifestPath = resolve(distDir, 'manifest.json')
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))

  // 刷新 agent 入口文档的计数快照(文件或标记缺失即抛错,不静默跳过)
  const indexPath = resolve(root, 'graph/index.md')
  const indexSrc = readFileSync(indexPath, 'utf8')
  writeFileSync(indexPath, replaceStatsBlock(indexSrc, renderStatsBlock(result.stats, new Date().toISOString().slice(0, 10))))
  console.log('graph/index.md 计数区块已刷新')

  // 体积哨兵：与 tools/kg/state/quality/trends.jsonl 上一条比较，骤减 >10% 告警（不阻断）
  // trends 为「提交采样」非「构建采样」：同日记录覆盖而非追加，避免本地每次 build 弄脏工作区
  const trendsDir = resolve(root, 'tools/kg/state/quality')
  const trendsPath = resolve(trendsDir, 'trends.jsonl')
  mkdirSync(trendsDir, { recursive: true })
  const today = new Date().toISOString().slice(0, 10)
  const existing = existsSync(trendsPath) ? readFileSync(trendsPath, 'utf8') : ''
  const prev = lastTrendLine(existing)
  const cur = { nodes: result.stats.nodes, edges: result.stats.edges }
  const warning = shrinkWarning(prev, cur)
  if (warning) console.warn(warning)
  const line = JSON.stringify({ date: today, ...cur })
  const lines = existing ? existing.split('\n') : []
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop()
  if (prev && prev.date === today) lines.pop() // 同日：替换最后一条记录
  lines.push(line)
  writeFileSync(trendsPath, lines.join('\n') + '\n')

  console.log(`build 完成: ${result.stats.nodes} nodes, ${result.stats.edges} edges -> dist/`)
  console.log(JSON.stringify(result.stats.byType))
  console.log(`manifest: ${manifest.files['graph.json']!.sha256.slice(0, 16)}… (version ${BUILD_VERSION})`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
