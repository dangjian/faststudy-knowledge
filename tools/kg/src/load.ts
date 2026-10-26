import { readFileSync, readdirSync } from 'node:fs'
import { resolve, join, extname } from 'node:path'
import { parse } from 'yaml'
import { globSync } from 'glob'
import { EntitySchema } from './schema/entities.js'
import { RelationSchema } from './schema/relations.js'
import type { Entity, RelationEdge, Ontology } from './schema/types.js'
import { loadOntology } from './ontology.js'
import { parseSupplement, parseItemsMd, entitiesFromItemsDoc } from './items_md.js'

export interface LoadedGraph {
  ontology: Ontology
  entities: Entity[]
  relations: RelationEdge[]
  entityFiles: Map<string, string>   // id -> 文件路径（报错定位）
  rootDir: string                    // 仓库根（sourceRef 为相对此处的路径，lint 据此校验存在性）
}

const ITEM_KEYS = ['words', 'phrases', 'sentences', 'characters'] as const
const KEY_TO_TYPE: Record<string, string> = {
  words: 'Word', phrases: 'Phrase', sentences: 'Sentence', characters: 'Character',
}
function expandItemFile(obj: Record<string, unknown>, file: string): unknown[] {
  if (!ITEM_KEYS.some(k => k in obj)) return [obj]
  const out: unknown[] = []
  for (const k of ITEM_KEYS) {
    const arr = obj[k]
    if (!Array.isArray(arr)) continue
    for (const item of arr) {
      const declared = (item as { type?: unknown })?.type
      if (typeof declared === 'string' && declared !== KEY_TO_TYPE[k]) {
        const id = (item as { id?: unknown })?.id
        throw new Error(`items 展开 type 不匹配 ${file}: 键 ${k} 下条目 ${String(id)} 声明 type 为 ${declared}`)
      }
      out.push({ ...item, type: KEY_TO_TYPE[k] })
    }
  }
  return out
}

function readYaml<T>(file: string): T {
  return parse(readFileSync(file, 'utf8')) as T
}

interface TbSection { id: string; title: string; order: number; pageRange?: [number, number] }
interface TbChapter {
  id: string; title: string; order: number; pageRange: [number, number]
  bodyHasPageMarkers?: boolean; sections?: TbSection[]
}
interface TbYaml {
  textbookId: string; title: string; grade: string; term: string; subject: string
  publisher: string; totalPages: number; imageOffset?: number; standardEdition?: '2011版' | '2022版'
  origin: 'textbook' | 'extension'; source?: string
  chapters?: TbChapter[]
}

// structure 层为派生:Textbook/Chapter/Section 由书级 index.md 的 front-matter 即时生成,不再有源文件
// （2026-08-28 content 去 YAML 化：原 textbook.yaml 折入 index.md front-matter）
export function deriveStructure(rootDir: string): { entities: Entity[]; files: Map<string, string> } {
  const entities: Entity[] = []
  const files = new Map<string, string>()
  // 书级 index.md 与章节级 chapters/C<n>/index.md 同名，glob 后需滤掉后者
  const paths = globSync(resolve(rootDir, 'content/**/index.md')).filter(p => !p.includes('/chapters/'))
  for (const file of paths.sort()) {
    const tb = parseSupplement(readFileSync(file, 'utf8')).frontmatter as unknown as TbYaml
    if (!tb?.textbookId || !Array.isArray(tb.chapters)) continue // 未回填 chapters 的教材跳过
    const conforming = tb.chapters.every(ch => typeof ch.id === 'string' && (ch.sections ?? []).every(s => typeof s.id === 'string'))
    if (!conforming) {
      const anyId = tb.chapters.some(ch => typeof ch.id === 'string' || (ch.sections ?? []).some(s => typeof s.id === 'string'))
      // 全部无 id:旧格式(chapter:/section: 键)视为未回填,跳过--Task 5 回填新格式后生效
      if (!anyId) continue
      // 部分有 id 部分没有:只能是回填脚本出错,fail fast
      throw new Error(`书级 index.md 混合格式(部分 chapter/section 缺 id) ${file}`)
    }
    const rel = file.slice(resolve(rootDir).length + 1)
    const dir = rel.replace(/\/index\.md$/, '')
    const push = (e: unknown): void => {
      const parsed = EntitySchema.safeParse(e)
      if (!parsed.success) {
        throw new Error(`schema 校验失败 ${file}: ${parsed.error.message}`)
      }
      entities.push(parsed.data as Entity)
      files.set(parsed.data.id, file)
    }
    push({
      id: tb.textbookId, type: 'Textbook', title: tb.title, grade: tb.grade, term: tb.term,
      subject: tb.subject, publisher: tb.publisher, totalPages: tb.totalPages,
      ...(tb.imageOffset !== undefined ? { imageOffset: tb.imageOffset } : {}),
      ...(tb.standardEdition ? { standardEdition: tb.standardEdition } : {}),
      origin: tb.origin, ...(tb.source ? { source: tb.source } : {}), sourceRef: rel,
    })
    for (const ch of tb.chapters) {
      const chId = `${tb.textbookId}-${ch.id}`
      push({
        id: chId, type: 'Chapter', textbookId: tb.textbookId, title: ch.title, order: ch.order,
        pageRange: ch.pageRange,
        ...(ch.bodyHasPageMarkers !== undefined ? { bodyHasPageMarkers: ch.bodyHasPageMarkers } : {}),
        sourceRef: rel,
      })
      for (const s of ch.sections ?? []) {
        push({
          id: `${chId}-${s.id}`, type: 'Section', chapterId: chId, textbookId: tb.textbookId,
          title: s.title, order: s.order, pageRange: s.pageRange,
          // 原书页图直链：构建期按 KG_PAGE_IMAGE_BASE_URL 派生（页图号 = 印刷页码 + imageOffset）。
          // 私有侧注入基址后生成 pageImages；未设置 = 该可选功能显式关闭，不产字段。
          ...(process.env.KG_PAGE_IMAGE_BASE_URL && tb.imageOffset !== undefined && s.pageRange
            ? {
                pageImages: Array.from(
                  { length: s.pageRange[1] - s.pageRange[0] + 1 },
                  (_, i) => `${process.env.KG_PAGE_IMAGE_BASE_URL}/textbooks/${tb.textbookId}/pages/${s.pageRange![0] + i + tb.imageOffset!}.jpg`,
                ),
              }
            : {}),
          sourceRef: `${dir}/chapters/${ch.id}/sections/${s.id}.md`,
        })
      }
    }
  }
  return { entities, files }
}

// content 层词书实体（Word/Phrase/Sentence/Character）由章节文档文末的词书四类区块派生（v4）：
// 扫 content/**/sections/*.md 与 content/**/chapters/C*/index.md（章级汉字表）。
// 插图区块降级为纯文本图注、解题模型/笔记/总结区块由消费方直读正文，均不再派生实体。
export function loadContentItems(rootDir: string): { entities: Entity[]; files: Map<string, string> } {
  const entities: Entity[] = []
  const files = new Map<string, string>()
  const paths = [
    ...globSync(resolve(rootDir, 'content/**/sections/*.md')),
    ...globSync(resolve(rootDir, 'content/**/chapters/C*/index.md')),
  ]
  for (const file of paths.sort()) {
    const rel = file.slice(resolve(rootDir).length + 1)
    const doc = parseItemsMd(readFileSync(file, 'utf8'), rel)
    for (const e of entitiesFromItemsDoc(doc, rel)) {
      const parsed = EntitySchema.safeParse(e)
      if (!parsed.success) throw new Error(`schema 校验失败 ${rel}: ${parsed.error.message}`)
      entities.push(parsed.data as Entity)
      files.set(parsed.data.id, rel)
    }
  }
  return { entities, files }
}

export function loadEntities(graphDir: string): { entities: Entity[]; files: Map<string, string> } {
  const entities: Entity[] = []
  const files = new Map<string, string>()
  const pattern = resolve(graphDir, 'entities/**/*.yaml')
  const paths = globSync(pattern)
  for (const file of paths.sort()) {
    const raw = readYaml<unknown>(file)
    const items = Array.isArray(raw) ? raw : expandItemFile(raw as Record<string, unknown>, file)
    for (const item of items) {
      const parsed = EntitySchema.safeParse(item)
      if (!parsed.success) {
        throw new Error(`schema 校验失败 ${file}: ${parsed.error.message}`)
      }
      entities.push(parsed.data as Entity)
      files.set(parsed.data.id, file)
    }
  }
  return { entities, files }
}

export function loadRelations(graphDir: string): RelationEdge[] {
  const relations: RelationEdge[] = []
  const relDir = resolve(graphDir, 'relations')
  let paths: string[] = []
  try { paths = readdirSync(relDir).filter(f => extname(f) === '.yaml').map(f => join(relDir, f)) } catch { /* 无 relations 目录 */ }
  for (const file of paths.sort()) {
    const type = file.replace(/.*\//, '').replace(/\.yaml$/, '')
    const list = readYaml<unknown[]>(file)
    for (const item of list ?? []) {
      const edge = { type: type as RelationEdge['type'], ...(item as object) } as unknown as RelationEdge
      const parsed = RelationSchema.safeParse(edge)
      if (!parsed.success) {
        throw new Error(`关系校验失败 ${file}: ${parsed.error.message}`)
      }
      relations.push(parsed.data)
    }
  }
  return relations
}

export function loadGraph(rootDir: string): LoadedGraph {
  const graphDir = resolve(rootDir, 'graph')
  const ontology = loadOntology(resolve(graphDir, 'ontology.yaml'))
  const entities: Entity[] = []
  const files = new Map<string, string>()
  const sources = [loadEntities(graphDir), deriveStructure(rootDir), loadContentItems(rootDir)]
  for (const src of sources) {
    entities.push(...src.entities)
    for (const [id, f] of src.files) files.set(id, f)
  }
  const relations = loadRelations(graphDir)
  return { ontology, entities, relations, entityFiles: files, rootDir: resolve(rootDir) }
}
