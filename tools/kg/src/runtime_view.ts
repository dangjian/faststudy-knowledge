import type { Entity, EntityType, Graph, RelationEdge } from './schema/types.js'

/**
 * dist/graph.json 的运行时视图投影。
 *
 * dist 不是 YAML 源的镜像,而是「应用侧运行时视图」——唯一的运行时消费者是下游应用侧
 * (kg-review.service 与 learning agent 的 4 个 kg_* 工具)。knowledge 侧的所有工具
 * (eval / kg_ask / query / review / lint) 都走 loadGraph 读 YAML 源,不读 dist。
 *
 * 因此建库期的治理与溯源字段(standards / evidence / centrality / gradeRange /
 * aliases / category / publisher / totalPages …)留在 YAML 源即可,不进 dist:
 * 它们占约 1.8 MB 却无人在运行时读取。需要全保真时走 loadGraph,dist 随时可由
 * kg:build 重建,所以刻意不另存一份全量 JSON。
 */

/** 所有类型共有;sourceRef 必须保留——kg-review 的 VOCAB_REF 正则靠它筛词汇 */
const COMMON_FIELDS = ['id', 'type', 'sourceRef'] as const

// v4（章节区块融合）后 build 即 runtime：Figure/ExamModel 已退役，投影期不再剔除任何整类节点；
// 字段保留为空数组，维持投影契约形状（manifest.runtimeView.droppedTypes）稳定
const DROPPED_TYPES: readonly EntityType[] = []

const RUNTIME_FIELDS: Record<EntityType, readonly string[]> = {
  Textbook: ['title', 'subject', 'grade', 'term', 'origin', 'imageOffset'],
  Chapter: ['title', 'textbookId', 'order', 'pageRange'],
  Section: ['title', 'chapterId', 'textbookId', 'order', 'pageRange', 'pageImages'],
  // standards / gradeRange 进 dist（2026-10-26）：课标对齐与学段是**数据本身**，
  // 外部使用者（教研、课程对齐、跨库 join）需要它；此前按「无运行时消费者」裁掉，
  // 等于让开源数据集丢掉了最有价值的一列。centrality/evidence 仍不进（纯治理派生）。
  Concept: ['title', 'subject', 'explanation', 'misconceptions', 'standards', 'gradeRange', 'conceptType', 'masteryCriteria'],
  Word: ['word', 'ipa', 'pos', 'meaning'],
  Phrase: ['en', 'cn'],
  Sentence: ['english', 'cn'],
  Character: ['char', 'pinyin', 'definition', 'example'],
}

/**
 * 边只留拓扑 + 复核档位。
 * `reviewed` 必须进 dist:下游先修闭包要按档位收口(全库先修复核（2026-08） 逐条复核 vs 其后抽样批次),
 * 而运行时消费者只读 dist、拿不到 YAML 源。`strength` 仍不进(dist 侧无人读)。
 */
const EDGE_FIELDS = ['type', 'from', 'to', 'reviewed', 'strength'] as const

export interface RuntimeViewMeta {
  droppedTypes: readonly string[]
  fieldsByType: Record<string, readonly string[]>
  commonFields: readonly string[]
  edgeFields: readonly string[]
}

export function runtimeViewMeta(): RuntimeViewMeta {
  return {
    droppedTypes: DROPPED_TYPES,
    fieldsByType: { ...RUNTIME_FIELDS },
    commonFields: COMMON_FIELDS,
    edgeFields: EDGE_FIELDS,
  }
}

function pick(node: Entity, fields: readonly string[]): Entity {
  const src = node as Record<string, unknown>
  const out: Record<string, unknown> = {}
  for (const k of COMMON_FIELDS) if (src[k] !== undefined) out[k] = src[k]
  for (const k of fields) if (src[k] !== undefined) out[k] = src[k]
  return out as unknown as Entity
}

/**
 * 按白名单投影出运行时视图。
 *
 * 未知节点类型直接抛错(CLAUDE.md §4.3 fail fast):新增实体类型时必须有人显式决定
 * 它该不该进运行时。静默透传或静默丢弃都会退化成「agent 拿不到数据」这类难查的症状。
 */
export function projectRuntimeView(graph: Graph): Graph {
  const nodes: Entity[] = []
  for (const n of graph.nodes) {
    const fields = RUNTIME_FIELDS[n.type]
    if (!fields) {
      throw new Error(`runtime_view: 未知实体类型 ${n.type}(节点 ${n.id})——请在 RUNTIME_FIELDS 中显式声明它的运行时字段`)
    }
    nodes.push(pick(n, fields))
  }

  return { nodes, edges: graph.edges.map(projectEdge) }
}

/** 边按 EDGE_FIELDS 白名单投影——与 manifest 里公布的 edgeFields 必须同源 */
function projectEdge(e: RelationEdge): RelationEdge {
  const src = e as unknown as Record<string, unknown>
  const out: Record<string, unknown> = {}
  for (const k of EDGE_FIELDS) if (src[k] !== undefined) out[k] = src[k]
  return out as unknown as RelationEdge
}
