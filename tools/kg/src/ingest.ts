import { writeFileSync, mkdirSync, existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { parse, stringify } from 'yaml'
import { globSync } from 'glob'
import type { Entity, RelationEdge } from './schema/types.js'
import { requoteBoolWords } from './yaml_utils.js'
import { renderItemsMd } from './items_md.js'

// 词书四类（v4：Figure 退役，插图区块为纯文本图注，不再由抽取产物生成）
const RENDER_TABLE_SECTIONS_TYPES = new Set(['Word', 'Phrase', 'Sentence', 'Character'])

export interface SectionInput {
  sectionId: string
  pageRange: [number, number]
  images: string[]   // 页面图路径
}

export interface ExtractResult {
  prose: string
  concepts: Entity[]
  items: Entity[]
  relations: RelationEdge[]
}

// 注入式：真实实现调 LLM；测试用 fake
export interface Extractor {
  extract(input: SectionInput, skillDir: string): Promise<ExtractResult>
}

export interface IngestOptions {
  force?: boolean
  contentDir: string   // 该 section prose 输出目录(chapters/C<n>/sections)
  graphDir: string
  skillDir: string
}

// 词书区块（## 单词/短语/句子/汉字）按约定只在文末：从首个词书区块标题起整段替换，保证重跑幂等。
// 注意：该替换假定词书区块之后没有其他需保留的区块（如插图图注）；针对新摄入的 section 文件成立，
// 不要对已含迁移数据的历史书重跑 ingest。
const WORDBOOK_BLOCK_RE = /^## (单词|短语|句子|汉字)\s*$/m

function upsertWordbookBlocks(src: string, blocks: string): string {
  const m = src.match(WORDBOOK_BLOCK_RE)
  const base = m && m.index !== undefined ? src.slice(0, m.index) : src
  return base.replace(/\n*$/, '\n\n') + blocks
}

export function writeExtract(section: SectionInput, result: ExtractResult, opts: IngestOptions): void {
  // content section.md
  // prose 为空表示正文已由上游落盘（注入管线第 ② 步 book_apply.py 已写好 sections/S<m>.md），
  // 此时不建档——否则会在 contentDir 里多出一个空壳 md，且命名与既有布局不一致
  const secPath = resolve(opts.contentDir, `${section.sectionId}.md`)
  if (result.prose !== '' && (!existsSync(secPath) || opts.force)) {
    const front = `---\nsectionId: ${section.sectionId}\npageRange: [${section.pageRange[0]}, ${section.pageRange[1]}]\n---\n`
    mkdirSync(dirname(secPath), { recursive: true })
    writeFileSync(secPath, front + result.prose)
  }
  // concepts（学科聚合文件，按 id 幂等追加；force 时同 id 替换）
  const bySubject = new Map<string, Entity[]>()
  for (const c of result.concepts) {
    const subject = c.id.split(':')[1]!
    if (!bySubject.has(subject)) bySubject.set(subject, [])
    bySubject.get(subject)!.push(c)
  }
  for (const [subject, list] of bySubject) {
    const f = resolve(opts.graphDir, `entities/concepts/${subject}.yaml`)
    let existing: Entity[] = []
    if (existsSync(f)) existing = (parse(readFileSync(f, 'utf8')) as Entity[]) ?? []
    const incoming = new Set(list.map(c => c.id))
    const seen = new Set(existing.map(e => e.id))
    const merged = opts.force
      ? [...existing.filter(e => !incoming.has(e.id)), ...list]
      : [...existing, ...list.filter(c => !seen.has(c.id))]
    merged.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    mkdirSync(dirname(f), { recursive: true })
    writeFileSync(f, requoteBoolWords(stringify(merged)))
  }
  // 词书四类实体（v4）：渲染成文末区块追加到 section md，不再写独立 items 文件。
  // 未知类型 fail-loud；原习题锚点段写入随 2026-09-27 刷题层移除删除。
  if (result.items.length > 0) {
    const tables: Record<string, Record<string, unknown>[]> = {}
    for (const it of result.items) {
      if (!tables[it.type]) {
        if (!RENDER_TABLE_SECTIONS_TYPES.has(it.type)) throw new Error(`未知 item 类型: ${it.type} (id: ${it.id})`)
        tables[it.type] = []
      }
      const { type: _t, sourceRef: _s, ...fields } = it as unknown as Record<string, unknown>
      tables[it.type]!.push({ id: it.id, ...fields })
    }
    const blocks = renderItemsMd(tables)
    if (blocks) {
      if (!existsSync(secPath)) {
        // 无 prose 可写而节文件又不存在：以 front-matter 建最小载体，再挂区块
        mkdirSync(dirname(secPath), { recursive: true })
        writeFileSync(secPath, `---\nsectionId: ${section.sectionId}\npageRange: [${section.pageRange[0]}, ${section.pageRange[1]}]\n---\n`)
      }
      const existing = readFileSync(secPath, 'utf8')
      // 已有词书区块且非 force：跳过（与旧 items 文件 !exists 跳过语义对齐，防重复追加）
      if (!WORDBOOK_BLOCK_RE.test(existing) || opts.force) {
        writeFileSync(secPath, upsertWordbookBlocks(existing, blocks))
      }
    }
  }
  // relations（追加，去重 from+to+type）
  appendRelations(result.relations, opts.graphDir)
}

function appendRelations(edges: RelationEdge[], graphDir: string): void {
  const byType = new Map<string, RelationEdge[]>()
  for (const e of edges) {
    if (!byType.has(e.type)) byType.set(e.type, [])
    byType.get(e.type)!.push(e)
  }
  for (const [type, list] of byType) {
    const f = resolve(graphDir, `relations/${type}.yaml`)
    let existing: RelationEdge[] = []
    if (existsSync(f)) existing = parse(readFileSync(f, 'utf8')) as RelationEdge[] ?? []
    const seen = new Set(existing.map(e => `${e.from}->${e.to}`))
    const merged = [...existing, ...list.filter(e => !seen.has(`${e.from}->${e.to}`))]
    mkdirSync(dirname(f), { recursive: true })
    writeFileSync(f, stringify(merged))
  }
}

export async function ingest(sections: SectionInput[], extractor: Extractor, opts: IngestOptions): Promise<void> {
  const skillDir = opts.skillDir
  for (const s of sections) {
    const result = await extractor.extract(s, skillDir)
    writeExtract(s, result, opts)
  }
}

// ---- 内容注入管线第 ④ 步：从 extract JSON 落盘 ----
// 第 ③ 步（llm_extract_graph.py）只产 state/ingest/<textbookId>/extract/<sectionId>.json，
// 不碰图谱；本步是唯一写盘方。两段式的用意见 spec「决策 1/2」：LLM 的判断先落成可 diff、
// 可复核、可重放的中间文件，写盘全是确定性代码。

/** 从 extract 目录按 sectionId 读 JSON 的 Extractor。文件缺失即抛错，不静默跳过。 */
export class FileExtractor implements Extractor {
  constructor(private readonly dir: string) {}

  async extract(input: SectionInput): Promise<ExtractResult> {
    const f = resolve(this.dir, `${input.sectionId}.json`)
    if (!existsSync(f)) {
      throw new Error(`找不到 extract JSON: ${f}。先跑 llm_extract_graph.py 产出第 ③ 步结果`)
    }
    const raw = JSON.parse(readFileSync(f, 'utf8')) as Partial<ExtractResult> & { status?: string }
    if (raw.status && raw.status !== 'ok') {
      throw new Error(`${f}: status=${raw.status}，不是可用的抽取结果`)
    }
    for (const k of ['concepts', 'items', 'relations'] as const) {
      if (!Array.isArray(raw[k])) throw new Error(`${f}: 缺 ${k} 数组`)
    }
    return { prose: raw.prose ?? '', concepts: raw.concepts!, items: raw.items!, relations: raw.relations! }
  }
}

function usage(): never {
  console.error('用法: pnpm ingest -- <knowledge 仓库根> --textbook <textbookId> [--force]')
  console.error('前置：第 ③ 步已产出 state/ingest/<textbookId>/extract/*.json')
  process.exit(2)
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2).filter(a => a !== '--')
  const root = resolve(argv.find(a => !a.startsWith('--')) ?? process.cwd())
  const tbIdx = argv.indexOf('--textbook')
  const textbookId = tbIdx >= 0 ? argv[tbIdx + 1] : undefined
  if (!textbookId) usage()

  const extractDir = resolve(root, 'tools/kg/state/ingest', textbookId, 'extract')
  if (!existsSync(extractDir)) throw new Error(`extract 目录不存在: ${extractDir}`)
  const files = readdirSync(extractDir).filter(f => f.endsWith('.json')).sort()
  if (files.length === 0) throw new Error(`${extractDir} 下没有 extract JSON`)

  const bookDir = globSync(resolve(root, `content/*/*/*/${textbookId}`))[0]
  if (!bookDir) throw new Error(`content/ 下找不到教材目录 ${textbookId}。先跑第 ② 步 book_apply.py`)

  const sections: SectionInput[] = files.map(f => {
    const sectionId = f.replace(/\.json$/, '')
    const raw = JSON.parse(readFileSync(resolve(extractDir, f), 'utf8')) as { pageRange?: [number, number] }
    const m = sectionId.match(/-(C\d+)-S\w+$/)
    if (!m) throw new Error(`extract JSON 文件名不是 <textbookId>-C<n>-S<m> 形态: ${f}`)
    return {
      sectionId,
      // pageRange 恒为教材页号（页码语义裁决（2026-08） 裁决）；扩展知识无页码，用 [0,0] 占位不落进任何实体
      pageRange: raw.pageRange ?? [0, 0],
      images: [],
    }
  })

  const chapterOf = (sectionId: string): string => sectionId.match(/-(C\d+)-S\w+$/)![1]!
  for (const s of sections) {
    await ingest([s], new FileExtractor(extractDir), {
      force: argv.includes('--force'),
      contentDir: resolve(bookDir, 'chapters', chapterOf(s.sectionId), 'sections'),
      graphDir: resolve(root, 'graph'),
      skillDir: resolve(root, 'tools/kg/skills'),
    })
  }
  console.log(`ingest 完成: ${sections.length} 个 section -> ${textbookId}`)
  console.log('下一步：pnpm kg:lint && pnpm kg:build，再用 kg:ask 端到端抽查')
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((e: Error) => {
    console.error(e.message)
    process.exit(1)
  })
}
