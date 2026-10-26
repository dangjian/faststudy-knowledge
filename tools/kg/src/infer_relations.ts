/**
 * infer_relations.ts — 确定性关系推导（无需 LLM）
 *
 * 从已有图谱（covered_by + 结构 Section + content 实体 sourceRef）推导两类关系：
 *
 *   1) demonstrates : Item(Word/Phrase/Sentence/Character) -> Concept
 *      推导：content 实体的 sourceRef 解析到某节 -> 该节 covered_by 的概念即被其演示。
 *      直接服务于"出题"（学习项演示概念）。
 *
 *   2) related : Concept -> Concept（同章聚类）
 *      推导：同一 Chapter 下的概念彼此相关，以章首概念为 anchor 建星形连线。
 *
 * prerequisite 已于 2026-08-27 停止推导（章节链骨架停产（2026-08））。原做法是「同科目按 (grade, term, chapter.order)
 * 排成章节序列，相邻章首概念之间加边」，即拿**章节顺序当先修顺序的代理**。该代理已被实测否决：
 * 同教材内 7474 条可判边里 70.4% 判不了、正确仅 6.4%，教材编排常「先讲结论再补原理」。
 * 实测本函数补出的边形如 `水的状态变化 → 光的折射`、`分裂生殖 → 人类活动对生物圈的影响`，纯噪声，
 * 且会持续污染正在人工治理的 prerequisite.yaml。恢复推导前须先有站得住的先修信号。
 *
 * part_of 需要概念层级语义，确定性不可得，跳过（留待 LLM Pass）。
 *
 * 用法：
 *   tsx src/infer_relations.ts -- <root> [--dry]
 */
import { resolve } from 'node:path'
import { writeFileSync } from 'node:fs'
import { stringify } from 'yaml'
import { loadGraph } from './load.js'
import type { Entity, RelationEdge } from './schema/types.js'

const CONTENT_TYPES = new Set(['Word', 'Phrase', 'Sentence', 'Character'])

export interface InferResult {
  demoEdges: RelationEdge[]
  relatedEdges: RelationEdge[]
  demoBase: number
  relatedBase: number
}

export function inferRelations(g: ReturnType<typeof loadGraph>): InferResult {
  const sectionById = new Map<string, Entity>()
  for (const e of g.entities) {
    if (e.type === 'Section') sectionById.set(e.id, e)
  }

  // covered_by: section -> concepts
  const conceptsBySection = new Map<string, string[]>()
  for (const r of g.relations) {
    if (r.type === 'covered_by') {
      const arr = conceptsBySection.get(r.to) ?? []
      arr.push(r.from); conceptsBySection.set(r.to, arr)
    }
  }

  // 从 content 实体的 sourceRef 重构 sectionId（兼容 S1.md 与 C1-S1.md 两种命名）
  function sectionIdFromRef(ref: string): string | null {
    const m = ref.match(/\/([^/]+)\/chapters\/(C\d+)\/sections\/(.+?)\.md$/)
    if (!m) return null
    const sm = m[3].match(/S(\d+)/)
    if (!sm) return null
    return `${m[1]}-${m[2]}-S${sm[1]}`
  }

  // ===== 1) demonstrates（词义精确匹配，避免全连接爆炸）=====
  // 概念可匹配串：title + aliases（小写）
  const conceptNeedles = new Map<string, string[]>()
  for (const e of g.entities) {
    if (e.type !== 'Concept') continue
    const needles = [String((e as any).title ?? ''), ...((e as any).aliases ?? []).map(String)].map(s => s.toLowerCase()).filter(Boolean)
    conceptNeedles.set(e.id, needles)
  }
  // 收集每个 section 的 content 实体
  const sectionItems = new Map<string, Entity[]>()
  for (const e of g.entities) {
    if (!CONTENT_TYPES.has(e.type) || !e.sourceRef) continue
    const sid = sectionIdFromRef(e.sourceRef)
    if (!sid || !sectionById.has(sid)) continue
    const arr = sectionItems.get(sid) ?? []
    arr.push(e); sectionItems.set(sid, arr)
  }
  function itemText(e: Entity): string {
    const o = e as any
    const parts = [o.word, o.meaning, o.en, o.cn, o.english, o.char, o.definition, o.example]
    return parts.filter(Boolean).join(' ').toLowerCase()
  }
  // 以文件里已有的边为基线：写回是并集而非覆盖。人工治理（章节链骨架停产（2026-08） 等）会往这两个文件里加边，
  // 覆盖写会把这些边连同历史边一起抹掉（实测 related 12182→7638、demonstrates 6629→3731）。
  const demos = new Set<string>()
  const demoEdges: RelationEdge[] = []
  for (const r of g.relations) {
    if (r.type !== 'demonstrates') continue
    demos.add(`${r.from}\t${r.to}`)
    demoEdges.push(r)
  }
  const demoBase = demoEdges.length
  for (const [sid, items] of sectionItems) {
    const concepts = conceptsBySection.get(sid); if (!concepts || !concepts.length) continue
    const needlesFor = concepts.map(c => ({ id: c, needles: conceptNeedles.get(c) ?? [] })).filter(x => x.needles.length)
    if (!needlesFor.length) continue
    for (const it of items) {
      const hay = itemText(it)
      if (!hay) continue
      for (const { id, needles } of needlesFor) {
        if (needles.some(n => hay.includes(n))) {
          const key = `${it.id}\t${id}`
          if (demos.has(key)) continue
          demos.add(key)
          demoEdges.push({ type: 'demonstrates', from: it.id, to: id } as RelationEdge)
        }
      }
    }
  }

  // ===== 2) related (同章星形) =====
  const chapterConcepts = new Map<string, string[]>() // 保序、去重
  for (const r of g.relations) {
    if (r.type !== 'covered_by') continue
    const sec = sectionById.get(r.to); if (!sec) continue
    const chId = (sec as any).chapterId as string | undefined; if (!chId) continue
    const arr = chapterConcepts.get(chId) ?? []
    if (!arr.includes(r.from)) arr.push(r.from)
    chapterConcepts.set(chId, arr)
  }
  const relatedSet = new Set<string>()
  const relatedEdges: RelationEdge[] = []
  for (const r of g.relations) {
    if (r.type !== 'related') continue
    // related 语义无向：两个朝向都登记，避免推导出已存在边的反向副本
    relatedSet.add(`${r.from}\t${r.to}`)
    relatedSet.add(`${r.to}\t${r.from}`)
    relatedEdges.push(r)
  }
  const relatedBase = relatedEdges.length
  for (const concepts of chapterConcepts.values()) {
    if (concepts.length < 2) continue
    const anchor = concepts[0]
    for (let i = 1; i < concepts.length; i++) {
      const key = `${anchor}\t${concepts[i]}`
      if (relatedSet.has(key)) continue
      relatedSet.add(key)
      relatedEdges.push({ type: 'related', from: anchor, to: concepts[i] } as RelationEdge)
    }
  }

  return { demoEdges, relatedEdges, demoBase, relatedBase }
}

function main() {
  const args = process.argv.slice(2)
  const dry = args.includes('--dry')
  const root = resolve(args.find(a => !a.startsWith('-')) ?? process.cwd())
  const { demoEdges, relatedEdges, demoBase, relatedBase } = inferRelations(loadGraph(root))

  console.log(`[dry=${dry}]`)
  console.log(`  demonstrates : ${demoBase} 条已有 +${demoEdges.length - demoBase} 条新推导 = ${demoEdges.length}`)
  console.log(`  related      : ${relatedBase} 条已有 +${relatedEdges.length - relatedBase} 条新推导 = ${relatedEdges.length}`)
  console.log(`  prerequisite : 跳过 (章节顺序不是可靠的先修信号,见 章节链骨架停产（2026-08）)`)
  console.log(`  part_of      : 跳过 (需 LLM 语义)`)

  if (dry) return

  const relDir = resolve(root, 'graph/relations')
  // demonstrates / related: 写入「已有 ∪ 新推导」。绝不可改回覆盖写——文件里已含人工治理产出的边。
  writeFileSync(resolve(relDir, 'demonstrates.yaml'),
    `# 关系：学习项演示概念 (demonstrates)\n# 格式: from: <Item ID>, to: <Concept ID>\n# 由 tools/kg/src/infer_relations.ts 从 content 实体 sourceRef 确定性推导\n` +
    stringify(demoEdges.map(e => ({ from: e.from, to: e.to }))))
  writeFileSync(resolve(relDir, 'related.yaml'),
    `# 关系：相关关系 (related)\n# 格式: from: <Concept ID>, to: <Concept ID>\n# 由 tools/kg/src/infer_relations.ts 按同章聚类确定性推导\n` +
    stringify(relatedEdges.map(e => ({ from: e.from, to: e.to }))))
  console.log('  已写入 graph/relations/{demonstrates,related}.yaml')
}

if (import.meta.url === `file://${process.argv[1]}`) main()
