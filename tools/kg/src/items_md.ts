import { parse } from 'yaml'
import type { Entity } from './schema/types.js'

// section md / 章 index md = content v4 的唯一内容载体（章节区块模型）：
// 教材原文之后按固定顺序追加文末区块（## 汉字/单词/短语/句子/插图/解题模型/笔记/总结）。
// 本模块职责：
//   读端：扫描文末词书四类区块（## 单词/短语/句子/汉字）表格，派生四类实体（学情锚点）。
//         ## 插图 已降级为纯文本图注、## 解题模型/笔记/总结 由消费方直读正文，均不派生实体。
//         历史 items md 的 ## 习题 锚点段已全库剥离（2026-09-27 刷题层移除），出现即历史文件回流，fail-loud。
//   写端：ingest 把词书四类表格渲染成区块文本，追加到 section md 文末。
// 表格首列为完整实体 id（各科 id 形态不统一，不可推导）；单元格转义 `|`->`\|`，换行/数组以 <br> 连接。
// 与 python 写入端必须保持同构，解析失败即抛错（Fail Loud）。

// front-matter(yaml) + 正文 的通用切分（书级 index.md / 节 md / 旧 supplements md 同构）
export interface SupplementDoc {
  frontmatter: Record<string, unknown>
  body: string
}

export function parseSupplement(text: string): SupplementDoc {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
  if (!m) return { frontmatter: {}, body: text.trim() }
  return { frontmatter: (parse(m[1]) as Record<string, unknown>) ?? {}, body: m[2].trim() }
}

const SECTION_RE = /^## (.+)$/

// 中文节名 -> 实体类型与列字段（词书四类；与写端 RENDER_TABLE_SECTIONS 同构）
const TABLE_SECTIONS: Record<string, { type: string; cols: string[] }> = {
  单词: { type: 'Word', cols: ['id', 'word', 'ipa', 'pos', 'meaning'] },
  短语: { type: 'Phrase', cols: ['id', 'en', 'cn'] },
  句子: { type: 'Sentence', cols: ['id', 'english', 'cn'] },
  汉字: { type: 'Character', cols: ['id', 'char', 'pinyin', 'definition', 'example'] },
}

export interface ItemsDoc {
  sectionId?: string   // 节 md front-matter 有；章 index md 只有 chapterId，可缺省
  tables: Record<string, Record<string, unknown>[]>   // 实体类型 -> 原始字段对象
}

function uncell(v: string): string {
  return v.replace(/\\\|/g, '|')
}

/** 单元格 -> 字段值：空串视为缺省；数组字段以 <br> 还原 */
function fieldValue(type: string, col: string, v: string): unknown {
  if (v === '') return undefined
  const unescaped = uncell(v).replace(/<br>/g, '\n')
  if (type === 'Sentence' && col === 'english') return uncell(v).split('<br>')
  return unescaped
}

/** 从 section md / 章 index md 文本扫描词书四类区块表格（原文与其他区块一律跳过） */
export function parseItemsMd(text: string, file: string): ItemsDoc {
  const { frontmatter, body } = parseSupplement(text)
  const doc: ItemsDoc = {
    sectionId: typeof frontmatter.sectionId === 'string' ? frontmatter.sectionId : undefined,
    tables: {},
  }

  let mode: { type: string; cols: string[] } | null = null

  for (const line of body.split('\n')) {
    const secMatch = line.match(SECTION_RE)
    if (secMatch) {
      const name = secMatch[1]!.trim()
      if (name === '习题') {
        // 刷题层已移除（2026-09-27）：md 不再允许习题段，出现即历史文件回流，fail loud
        // （教材原文里的「习题6.2」等小节标题不是精确的 ## 习题，不受此约束）
        throw new Error(`md 含已移除的 ## 习题 段（刷题层已裁撤）: ${file}`)
      }
      mode = TABLE_SECTIONS[name] ?? null
      if (mode) doc.tables[mode.type] = doc.tables[mode.type] ?? []
      continue
    }
    if (mode && line.startsWith('|')) {
      // 写入端每格左右各垫 1 个空格，解析时精确剥掉这 1 个，保留数据自身的前后空格
      const cells = line.slice(1, -1).split(/(?<!\\)\|/).map(c => c.replace(/^ /, '').replace(/ $/, ''))
      if (cells.every(c => /^-+$/.test(c))) continue   // 分隔行
      if (cells[0] === 'id') continue   // 表头行
      const obj: Record<string, unknown> = { type: mode.type }
      for (let i = 0; i < mode.cols.length; i++) {
        const v = fieldValue(mode.type, mode.cols[i]!, cells[i] ?? '')
        if (v !== undefined) obj[mode.cols[i]!] = v
      }
      doc.tables[mode.type]!.push(obj)
    } else if (mode && line.trim() !== '') {
      mode = null   // 非表格内容行：当前词书表格结束（空行容忍）
    }
  }
  return doc
}

/** 词书四类实体（Word/Phrase/Sentence/Character）；插图区块不派生实体（v4 降级纯文本图注） */
export function entitiesFromItemsDoc(doc: ItemsDoc, rel: string): Entity[] {
  const out: Entity[] = []
  for (const [type, items] of Object.entries(doc.tables)) {
    for (const item of items) {
      out.push({ ...item, sourceRef: rel } as unknown as Entity)
    }
  }
  return out
}

// ---- 写端（ingest 摄入用；区块追加到 section md 文末，不再写独立 items 文件 ----

const RENDER_TABLE_SECTIONS: { key: string; zh: string; type: string; cols: string[] }[] = [
  { key: 'Word', zh: '单词', type: 'Word', cols: ['id', 'word', 'ipa', 'pos', 'meaning'] },
  { key: 'Phrase', zh: '短语', type: 'Phrase', cols: ['id', 'en', 'cn'] },
  { key: 'Sentence', zh: '句子', type: 'Sentence', cols: ['id', 'english', 'cn'] },
  { key: 'Character', zh: '汉字', type: 'Character', cols: ['id', 'char', 'pinyin', 'definition', 'example'] },
]

function renderCell(v: unknown): string {
  if (v === undefined || v === null) return ''
  let s: string
  if (Array.isArray(v)) s = v.map(String).join('<br>')
  else if (typeof v === 'object') s = JSON.stringify(v)
  else s = String(v)
  return s.replace(/\|/g, '\\|').replace(/\n/g, '<br>')
}

/** 渲染词书四类区块文本（追加到 section md 文末；调用方负责与既有内容的空行衔接） */
export function renderItemsMd(tables: Record<string, Record<string, unknown>[]>): string {
  const out: string[] = []
  for (const { type, zh, cols } of RENDER_TABLE_SECTIONS) {
    const rows = tables[type] ?? []
    if (rows.length === 0) continue
    out.push(`\n## ${zh}\n\n| ${cols.join(' | ')} |\n| ${cols.map(() => '---').join(' | ')} |\n`)
    for (const row of rows) {
      out.push(`| ${cols.map(c => renderCell(row[c])).join(' | ')} |\n`)
    }
  }
  return out.join('')
}
