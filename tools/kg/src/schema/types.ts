export type EntityType =
  | 'Textbook' | 'Chapter' | 'Section'
  | 'Concept'
  | 'Word' | 'Phrase' | 'Sentence' | 'Character'

export type RelationType =
  | 'prerequisite' | 'related' | 'part_of' | 'demonstrates' | 'covered_by'

export interface BaseEntity {
  id: string
  type: EntityType
  sourceRef?: string
}

export interface TextbookEntity extends BaseEntity {
  type: 'Textbook'
  title: string
  grade: string
  term: string
  subject: string
  publisher: string
  totalPages: number
}

export interface ChapterEntity extends BaseEntity {
  type: 'Chapter'
  textbookId: string
  title: string
  order: number
  pageRange: [number, number]
}

export interface SectionEntity extends BaseEntity {
  type: 'Section'
  chapterId: string
  textbookId: string
  title: string
  order: number
  pageRange: [number, number]
}

/** 教学类型（与实体判别字段 type 区分，故命名 conceptType） */
export const CONCEPT_TYPES = ['概念型', '程序型', '推理型', '应用型', '建模型'] as const
export type ConceptType = (typeof CONCEPT_TYPES)[number]

export interface ConceptEntity extends BaseEntity {
  type: 'Concept'
  subject: string
  title: string
  /** 教学类型：决定 agent 用哪种教法（定义/步骤/证明/情境/建模） */
  conceptType?: ConceptType
  /** 掌握标准：2–3 条可观察的「怎样算会了」，供 agent 判断掌握度 */
  masteryCriteria?: string[]
  aliases?: string[]
  explanation?: string
  category?: string
  misconceptions?: string[]      // 易错点：每条一句"错误认知 -> 纠正"
  confidence?: number            // 抽取置信度(0~1),政策见 skills/00-META.md §7
  // 以下为 build 阶段派生的增强字段（dist 产物中携带，graph/ 源文件通常留空）
  gradeRange?: string          // 如 "7" 或 "7-9"，由 covered_by→Section→Textbook.grade 推导
  standards?: string[]         // 国家课程标准对齐键（预留，待补数据）
  centrality?: number          // 先修 DAG 上的 PageRank 重要性（0-1，越高越基础）
}

export interface ItemEntity extends BaseEntity {
  type: 'Word' | 'Phrase' | 'Sentence' | 'Character'
  [key: string]: unknown
}

export type Entity =
  | TextbookEntity | ChapterEntity | SectionEntity
  | ConceptEntity | ItemEntity

export interface RelationEdge {
  type: RelationType
  from: string
  to: string
  strength?: 'hard' | 'soft'   // prerequisite 可选：先修强度
  reason?: string              // prerequisite 可选：先修理由
  /** prerequisite 可选：复核档位。audited=逐条判定过；sampled=批次抽样；缺省=未复核 */
  reviewed?: 'audited' | 'sampled'
}

export interface Graph {
  nodes: Entity[]
  edges: RelationEdge[]
}

export interface LintReport {
  errors: LintFinding[]
  warnings: LintFinding[]
}

export interface LintFinding {
  rule: string
  level: 'error' | 'warning'
  message: string
  ref?: string
}

export interface Ontology {
  entity_types: Record<string, { layer: string; storage: 'content' | 'graph' | 'derived'; properties: string[] }>
  relation_types: string[]
  relation_endpoints: Record<string, [string, string]>
}
