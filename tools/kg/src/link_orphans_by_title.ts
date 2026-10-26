import { resolve, dirname } from 'node:path'
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { parse, stringify } from 'yaml'
import { loadGraph } from './load.js'
import { sectionIdFromSourceRef } from './fix_covered_by.js'

const ROOT = resolve(process.argv.slice(2).find((a) => !a.startsWith('-')) ?? process.cwd())
const CONTENT = resolve(ROOT, 'content')
const GRAPH = resolve(ROOT, 'graph')

function sectionIdFromContentPath(p: string): string | null {
  return sectionIdFromSourceRef(p.replace(ROOT + '/', ''))
}

// 孤儿概念的 sourceRef 节号不可信（2026-09-18 重切对 unmapped 概念只改路径不改节号），但教材段可信：
// 只在同一本书内按标题检索，避免跨书/跨学段误挂（P1.1 发现 2，P1.2 裁决）
export function bookOfPath(p: string): string | null {
  return p.match(/content\/[^/]+\/[^/]+\/[^/]+\/([^/]+)\//)?.[1] ?? null
}

// 选标题出现次数最多、且能解析出已存在 sectionId 的节文件；平局取先出现者。
// 计数只看正文行、跳过 `|` 表格行（门 B 第 1 轮错例：插图残渣/生字表只在表格行命中）
export function bestSectionFor(
  title: string,
  pool: Array<{ f: string; text: string }>,
  sectionIds: Set<string>,
): string | null {
  let best: { f: string; count: number } | null = null
  for (const s of pool) {
    const prose = s.text.split('\n').filter((l) => !l.startsWith('|')).join('\n')
    const c = prose.split(title).length - 1
    if (c <= 0) continue
    const sid = sectionIdFromContentPath(s.f)
    if (!sid || !sectionIds.has(sid)) continue
    if (!best || c > best.count) best = { f: s.f, count: c }
  }
  return best?.f ?? null
}

// 概念文件按 pyyaml 风格缩进，整体 stringify 会重排全文件；只做行级替换：
// `- id: <cid>` 块内的顶层 `  sourceRef:` 行换成新值
export function rewriteSourceRefs(text: string, refs: Map<string, string>): string {
  let cid: string | null = null
  return text
    .split('\n')
    .map((line) => {
      const mId = line.match(/^- id:\s*(.+?)\s*$/)
      if (mId) cid = mId[1]!
      else if (cid && refs.has(cid) && /^  sourceRef:/.test(line)) return `  sourceRef: ${refs.get(cid)}`
      return line
    })
    .join('\n')
}

// 收集 content 下所有 section 文件内容
function collectSections(dir: string, acc: Array<{ f: string; text: string }>): void {
  for (const name of readdirSync(dir)) {
    const p = resolve(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) collectSections(p, acc)
    else if (/\/sections\/S.*\.md$/.test(p) || /\/appendix\/.*\.md$/.test(p)) {
      acc.push({ f: p, text: readFileSync(p, 'utf8') })
    }
  }
}

export function linkOrphansByTitle(): { linked: number; unmatched: number; fixedSrc: number } {
  const g = loadGraph(ROOT)
  const sectionIds = new Set(g.entities.filter((e) => e.type === 'Section').map((e) => e.id))
  const sections: Array<{ f: string; text: string }> = []
  collectSections(CONTENT, sections)
  const byBook = new Map<string, Array<{ f: string; text: string }>>()
  for (const s of sections) {
    const b = bookOfPath(s.f)
    if (!b) continue
    if (!byBook.has(b)) byBook.set(b, [])
    byBook.get(b)!.push(s)
  }

  const covFile = resolve(GRAPH, 'relations/covered_by.yaml')
  const existing: Array<{ from: string; to: string }> = existsSync(covFile)
    ? (parse(readFileSync(covFile, 'utf8')) as Array<{ from: string; to: string }>) ?? []
    : []
  const seen = new Set(existing.map((e) => `${e.from}->${e.to}`))

  let linked = 0
  const unmatched: string[] = []
  const refsBySubject = new Map<string, Map<string, string>>()

  for (const e of g.entities) {
    if (e.type !== 'Concept') continue
    const already = g.relations.some((r) => r.type === 'covered_by' && r.from === e.id)
    if (already) continue
    const title = (e as Record<string, any>).title as string
    if (!title) continue
    const book = e.sourceRef ? bookOfPath(e.sourceRef) : null
    const bestF = book ? bestSectionFor(title, byBook.get(book) ?? [], sectionIds) : null
    if (!bestF) {
      unmatched.push(e.id)
      continue
    }
    const sid = sectionIdFromContentPath(bestF)!
    const key = `${e.id}->${sid}`
    if (!seen.has(key)) {
      existing.push({ from: e.id, to: sid })
      seen.add(key)
    }
    // 修复 concept 的占位 sourceRef（v4：entities/concepts/<学科>.yaml 列表）
    const ref = bestF.replace(ROOT + '/', '')
    if (e.sourceRef !== ref) {
      const subj = e.id.split(':')[1]!
      if (!refsBySubject.has(subj)) refsBySubject.set(subj, new Map())
      refsBySubject.get(subj)!.set(e.id, ref)
    }
    linked++
  }

  let fixedSrc = 0
  for (const [subj, refs] of refsBySubject) {
    const cf = resolve(GRAPH, 'entities/concepts', `${subj}.yaml`)
    if (!existsSync(cf)) throw new Error(`概念文件不存在：${cf}`)
    writeFileSync(cf, rewriteSourceRefs(readFileSync(cf, 'utf8'), refs))
    fixedSrc += refs.size
  }

  if (linked > 0) {
    mkdirSync(dirname(covFile), { recursive: true })
    writeFileSync(covFile, stringify(existing))
  }
  return { linked, unmatched: unmatched.length, fixedSrc }
}

function main(): void {
  const r = linkOrphansByTitle()
  console.log(`link_orphans_by_title: 通过标题匹配链接 ${r.linked} 条; 修复 sourceRef ${r.fixedSrc} 个; 仍未匹配 ${r.unmatched} 条`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
