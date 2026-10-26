import { z } from 'zod'

const pageRange = z.tuple([z.number(), z.number()])

// 抽取置信度(0~1),仅 OCR/AI 抽取类实体携带;政策见 skills/00-META.md §7
const confidence = z.number().min(0).max(1).optional()

export const WordSchema = z.object({
  id: z.string(),
  type: z.literal('Word'),
  word: z.string(),
  ipa: z.string().optional(),
  pos: z.string().optional(),
  meaning: z.string(),
  confidence,
  sourceRef: z.string().optional(),
})

export const PhraseSchema = z.object({
  id: z.string(),
  type: z.literal('Phrase'),
  en: z.string(),
  cn: z.string(),
  confidence,
  sourceRef: z.string().optional(),
})

export const SentenceSchema = z.object({
  id: z.string(),
  type: z.literal('Sentence'),
  english: z.array(z.string()),
  cn: z.string(),
  confidence,
  sourceRef: z.string().optional(),
})

export const CharacterSchema = z.object({
  id: z.string(),
  type: z.literal('Character'),
  char: z.string(),
  pinyin: z.string().optional(),
  definition: z.string().optional(),
  example: z.string().optional(),
  confidence,
  sourceRef: z.string().optional(),
})

export const ConceptSchema = z.object({
  id: z.string(),
  type: z.literal('Concept'),
  subject: z.string(),
  title: z.string(),
  aliases: z.array(z.string()).optional(),
  explanation: z.string().optional(),
  category: z.string().optional(),
  misconceptions: z.array(z.string()).optional(),
  // 教学类型（与实体判别字段 type 区分）：概念型/程序型/推理型/应用型/建模型
  conceptType: z.enum(['概念型', '程序型', '推理型', '应用型', '建模型']).optional(),
  masteryCriteria: z.array(z.string()).optional(),
  confidence,
  sourceRef: z.string().optional(),
  // 以下为 build 阶段派生的增强字段（dist 产物中携带，graph/ 源文件通常留空）
  gradeRange: z.string().optional(),
  standards: z.array(z.string()).optional(),
  centrality: z.number().optional(),
})

export const SectionSchema = z.object({
  id: z.string(),
  type: z.literal('Section'),
  chapterId: z.string(),
  textbookId: z.string(),
  title: z.string(),
  order: z.number(),
  // 扩展知识（origin: extension）无纸质页码，故此处可缺省；
  // origin: textbook 的必填性由 lint rule 17 pageRange-required 强制，严格程度不减
  pageRange: pageRange.optional(),
  // 原书页图 CDN 直链（页图号 = 印刷页码 + imageOffset），load.ts 派生
  pageImages: z.array(z.string()).optional(),
  sourceRef: z.string().optional(),
})

export const ChapterSchema = z.object({
  id: z.string(),
  type: z.literal('Chapter'),
  textbookId: z.string(),
  title: z.string(),
  order: z.number(),
  pageRange: pageRange.optional(),
  // 章正文里有没有 `<!-- page N -->` 标记。摄入产物只剩页图、没有逐页文本时取不到标记，
  // 节页码便无从得知——此时唯一诚实的做法是缺省，而不是按字数摊派出一个看着对的假页码。
  // 显式记 false 的章，其 Section 由 lint rule 17 豁免 pageRange。
  // 由 export_sections.py 读正文生成，不手写：它是对源文件的可证伪陈述，不是许可开关。
  bodyHasPageMarkers: z.boolean().optional(),
  sourceRef: z.string().optional(),
})

export const TextbookSchema = z.object({
  id: z.string(),
  type: z.literal('Textbook'),
  title: z.string(),
  grade: z.string(),
  term: z.string(),
  subject: z.string(),
  publisher: z.string(),
  totalPages: z.number(),
  // 印刷页 → 扫描图片序号的偏移（图片页 = pageRange 里的印刷页 + imageOffset）。
  // optional 而非必填：43 本里 21 本（八下+九年级那批）的书级 front-matter 至今没声明，
  // 缺了就是缺了——消费方据此降级成书级链接，绝不拿 0 当默认值把页码算错。
  imageOffset: z.number().optional(),
  // 由封面/标题前缀推导：'2022版'（义务教育课程标准 2022 年版）或 '2011版'
  standardEdition: z.enum(['2011版', '2022版']).optional(),
  // 来源属性：textbook=原始教材（纸质教科书扫描入库），extension=扩展知识（EXT- 前缀的虚拟教材）
  // 每本书必须显式声明，不设默认值——「这本是不是教材」是被声明的事实，不是从 id 猜的
  origin: z.enum(['textbook', 'extension']),
  // 扩展知识的来源出处（书名/站点/作者等）。原始教材不填，由 lint rule 15 强制
  source: z.string().optional(),
  sourceRef: z.string().optional(),
})

export const EntitySchema = z.discriminatedUnion('type', [
  TextbookSchema, ChapterSchema, SectionSchema,
  ConceptSchema, WordSchema, PhraseSchema,
  SentenceSchema, CharacterSchema,
])
