import { resolve, dirname } from 'node:path'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { parse, stringify } from 'yaml'
import { loadGraph } from './load.js'

// 由 concept.sourceRef（content/<grade>/<term>/<subject>/<tbId>/chapters/Cn/sections/Sm.md）
// 推导 Section 实体 id：<tbId>-Cn-Sm；年级/册不设白名单（一至九年级、上/下/全一册）
export function sectionIdFromSourceRef(sr: string): string | null {
  const m = sr.match(/content\/[^/]+\/[^/]+\/[^/]+\/([^/]+)\/chapters\/(C\d+)\/sections\/(S\d+)\.md/)
  if (!m) return null
  return `${m[1]}-${m[2]}-${m[3]}`
}

export function fixCoveredBy(root: string): { added: number; skippedNoSrc: number; skippedNoSection: number } {
  const g = loadGraph(root)
  const sectionIds = new Set(g.entities.filter((e) => e.type === 'Section').map((e) => e.id))
  const covFile = resolve(root, 'graph/relations/covered_by.yaml')
  const existing: Array<{ from: string; to: string }> = existsSync(covFile)
    ? (parse(readFileSync(covFile, 'utf8')) as Array<{ from: string; to: string }>) ?? []
    : []
  const seen = new Set(existing.map((e) => `${e.from}->${e.to}`))
  const added: Array<{ from: string; to: string }> = []
  let skippedNoSrc = 0
  let skippedNoSection = 0

  for (const e of g.entities) {
    if (e.type !== 'Concept') continue
    const already = g.relations.some((r) => r.type === 'covered_by' && r.from === e.id)
    if (already) continue // 已有覆盖，保留
    if (!e.sourceRef) {
      skippedNoSrc++
      continue
    }
    const sid = sectionIdFromSourceRef(e.sourceRef)
    if (!sid || !sectionIds.has(sid)) {
      skippedNoSection++
      continue
    }
    const key = `${e.id}->${sid}`
    if (seen.has(key)) continue
    added.push({ from: e.id, to: sid })
    seen.add(key)
  }

  if (added.length) {
    const merged = [...existing, ...added]
    mkdirSync(dirname(covFile), { recursive: true })
    writeFileSync(covFile, stringify(merged))
  }
  return { added: added.length, skippedNoSrc, skippedNoSection }
}

function main(): void {
  const arg = process.argv.slice(2).find((a) => !a.startsWith('-'))
  const root = resolve(arg ?? process.cwd())
  const r = fixCoveredBy(root)
  console.log(
    `fix_covered_by: 新增 covered_by ${r.added} 条; 跳过(无 sourceRef) ${r.skippedNoSrc}; 跳过(section 不存在) ${r.skippedNoSection}`,
  )
}

if (import.meta.url === `file://${process.argv[1]}`) main()
