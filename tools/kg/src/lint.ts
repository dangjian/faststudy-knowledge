import { resolve, dirname } from 'node:path'
import { readFileSync, existsSync } from 'node:fs'
import { globSync } from 'glob'
import { loadGraph } from './load.js'
import type { LoadedGraph } from './load.js'
import type { LintReport, LintFinding } from './schema/types.js'
import { parseSupplement } from './items_md.js'
import { normTitle } from './title_norm.js'

function finding(rule: string, level: LintFinding['level'], message: string, ref?: string): LintFinding {
  return { rule, level, message, ref }
}

// rule 1 schema: load.ts 已用 zod 校验，此处汇总（load 失败会抛错；此函数兜底检查 type 字段）
function checkSchema(g: LoadedGraph, report: LintReport): void {
  for (const e of g.entities) {
    if (!e.type) report.errors.push(finding('schema', 'error', `实体缺 type 字段`, e.id))
  }
  for (const r of g.relations) {
    if (!r.from || !r.to) report.errors.push(finding('schema', 'error', `关系缺 from/to`, `${r.type}`))
  }
}

// rule 6 ontology-drift: 实体 type 与关系 type 必须在 ontology 注册
function checkOntologyDrift(g: LoadedGraph, report: LintReport): void {
  const eTypes = new Set(Object.keys(g.ontology.entity_types))
  const rTypes = new Set(g.ontology.relation_types)
  for (const e of g.entities) {
    if (!eTypes.has(e.type)) report.errors.push(finding('ontology-drift', 'error', `未注册的实体类型 ${e.type}`, e.id))
  }
  for (const r of g.relations) {
    if (!rTypes.has(r.type)) report.errors.push(finding('ontology-drift', 'error', `未注册的关系类型 ${r.type}`))
  }
}

// rule 5 ID-uniqueness
function checkIdUniqueness(g: LoadedGraph, report: LintReport): void {
  const seen = new Map<string, number>()
  for (const e of g.entities) seen.set(e.id, (seen.get(e.id) ?? 0) + 1)
  for (const [id, n] of seen) {
    if (n > 1) report.errors.push(finding('ID-uniqueness', 'error', `重复 ID 出现 ${n} 次`, id))
  }
}

// rule 2 relation-endpoint: 端点实体类型匹配 relation_endpoints
function checkRelationEndpoints(g: LoadedGraph, report: LintReport): void {
  const typeById = new Map(g.entities.map(e => [e.id, e.type]))
  const ep = g.ontology.relation_endpoints
  const contentTypes = new Set(['Word', 'Phrase', 'Sentence', 'Character'])
  for (const r of g.relations) {
    const spec = ep[r.type]
    if (!spec) continue
    const fromType = typeById.get(r.from)
    const toType = typeById.get(r.to)
    if (r.type === 'demonstrates') {
      if (fromType && !contentTypes.has(fromType))
        report.errors.push(finding('relation-endpoint', 'error', `demonstrates 的 from 必须是 content 实体，实际 ${fromType}`, r.from))
      if (toType !== 'Concept')
        report.errors.push(finding('relation-endpoint', 'error', `demonstrates 的 to 必须是 Concept，实际 ${toType}`, r.to))
    } else {
      // 端点声明支持联合类型（`Section|Chapter`），2026-10-25 起 covered_by 的 to 两级
      const expectFrom = spec[0].split('|')
      const expectTo = spec[1].split('|')
      if (!expectFrom.includes(fromType ?? '')) report.errors.push(finding('relation-endpoint', 'error', `${r.type} 的 from 类型应为 ${spec[0]}，实际 ${fromType}`, r.from))
      if (!expectTo.includes(toType ?? '')) report.errors.push(finding('relation-endpoint', 'error', `${r.type} 的 to 类型应为 ${spec[1]}，实际 ${toType}`, r.to))
    }
  }
}

// rule 3 referential-integrity: 关系端点实体必须存在
function checkReferentialIntegrity(g: LoadedGraph, report: LintReport): void {
  const ids = new Set(g.entities.map(e => e.id))
  for (const r of g.relations) {
    if (!ids.has(r.from)) report.errors.push(finding('referential-integrity', 'error', `from 端点不存在`, r.from))
    if (!ids.has(r.to)) report.errors.push(finding('referential-integrity', 'error', `to 端点不存在`, r.to))
  }
}

// rule 4 cycle: 有方向的边做 DAG 检查（related 无方向，不进 DAG）。
// part_of 语义是「from 是 to 的组成部分/子类/实例」（口径 B），方向唯一，
// A 隶属 B 且 B 隶属 A 不可能同时成立，故与 prerequisite 一样必须无环（sourceRef 归零治理（2026-09））。
const ACYCLIC_TYPES = ['prerequisite', 'part_of'] as const

function checkCycle(g: LoadedGraph, report: LintReport): void {
  for (const type of ACYCLIC_TYPES) {
    const edges = g.relations.filter(r => r.type === type)
    const indeg = new Map<string, number>()
    const adj = new Map<string, string[]>()
    const nodes = new Set<string>()
    for (const r of edges) { nodes.add(r.from); nodes.add(r.to) }
    for (const n of nodes) { indeg.set(n, 0); adj.set(n, []) }
    for (const r of edges) { adj.get(r.from)!.push(r.to); indeg.set(r.to, (indeg.get(r.to) ?? 0) + 1) }
    const queue = [...nodes].filter(n => indeg.get(n) === 0)
    let visited = 0
    while (queue.length) {
      const n = queue.shift()!
      visited++
      for (const m of adj.get(n) ?? []) {
        indeg.set(m, indeg.get(m)! - 1)
        if (indeg.get(m) === 0) queue.push(m)
      }
    }
    if (visited !== nodes.size) {
      report.errors.push(finding('cycle', 'error', `${type} 存在环（DAG 无环约束），涉及 ${nodes.size - visited} 个节点`))
    }
  }
}

// rule 7 orphan: 概念至少被一个 section covered_by，否则 warning
function checkOrphan(g: LoadedGraph, report: LintReport): void {
  const covered = new Set(g.relations.filter(r => r.type === 'covered_by').map(r => r.from))
  for (const e of g.entities) {
    if (e.type === 'Concept' && !covered.has(e.id)) {
      report.warnings.push(finding('orphan', 'warning', `概念未被任何 section 覆盖`, e.id))
    }
  }
}

// rule 8 sourceRef: 实体应有 sourceRef（缺失仅警告），指向的文件必须真实存在（error）
// 存在性此前从未被检查，2328 个悬空引用因此长期躲过 0/0 基线；content 去 YAML 化 +
// 残留清理后归零，遂按 sourceRef 归零治理（2026-09） 立下的「先修数据再加约束」纪律升为 error。
// sourceRef 可带片段锚点（如 items/C1-S1.md#exercise:xxx），校验路径时剥掉 # 之后的部分。
const SOURCE_REF_CAP = 10   // 同上，最多列 10 条，防刷屏

function checkSourceRef(g: LoadedGraph, report: LintReport): void {
  const exists = new Map<string, boolean>()
  const dangling: { id: string; message: string }[] = []
  for (const e of g.entities) {
    if (!e.sourceRef) {
      report.warnings.push(finding('sourceRef', 'warning', `实体缺 sourceRef`, e.id))
      continue
    }
    const path = e.sourceRef.split('#')[0]!
    let ok = exists.get(path)
    if (ok === undefined) {
      ok = existsSync(resolve(g.rootDir, path))
      exists.set(path, ok)
    }
    if (!ok) dangling.push({ id: e.id, message: `sourceRef 指向的文件不存在：${e.sourceRef}` })
  }
  for (const d of dangling.slice(0, SOURCE_REF_CAP)) {
    report.errors.push(finding('sourceRef', 'error', d.message, d.id))
  }
  if (dangling.length > SOURCE_REF_CAP) {
    report.errors.push(finding('sourceRef', 'error', `…等共 ${dangling.length} 条 sourceRef 悬空`))
  }
}

// rule 10 layer-placement: 文件归属必须匹配 ontology.storage 声明
// storage=graph 只能在 graph/entities/；storage=derived 不得出现在 graph/entities/；
// 另外 content/ 下不得出现任何 yaml（2026-08-28 content 去 YAML 化：content 只放 md，
// 学习项 yaml 折入 items/*.md 表格，textbook.yaml 折入书级 index.md front-matter）
function checkLayerPlacement(g: LoadedGraph, report: LintReport): void {
  const missingStorage = new Set<string>()
  for (const e of g.entities) {
    const storage = g.ontology.entity_types[e.type]?.storage
    const file = g.entityFiles.get(e.id)
    if (!storage) {
      if (!missingStorage.has(e.type)) {
        missingStorage.add(e.type)
        report.errors.push(finding('layer-placement', 'error', `ontology 中 ${e.type} 缺 storage 声明`, e.id))
      }
      continue
    }
    if (!file) continue
    const inGraph = file.includes('/graph/entities/')
    if (inGraph && storage !== 'graph')
      report.errors.push(finding('layer-placement', 'error', `storage=${storage} 的 ${e.type} 不应存放于 graph/entities/（${file}）`, e.id))
    if (!inGraph && storage === 'graph')
      report.errors.push(finding('layer-placement', 'error', `storage=graph 的 ${e.type} 应存放于 graph/entities/（${file}）`, e.id))
  }
  const contentYaml = globSync(resolve(g.rootDir, 'content/**/*.yaml'))
  for (const f of contentYaml.slice(0, 10)) {
    report.errors.push(finding('layer-placement', 'error', `content/ 下不得出现 yaml 文件（${f.slice(g.rootDir.length + 1)}）`))
  }
  if (contentYaml.length > 10) {
    report.errors.push(finding('layer-placement', 'error', `…等共 ${contentYaml.length} 个 yaml 出现在 content/ 下`))
  }
}

// rule 12 summary-height: summary/explanation 应是"一句话高度",疑似正文越界只作 informational warning
// 触发：字符数超阈值,或含步骤化信号（步骤/第 N 步/解法 N/行首编号）
const SUMMARY_MAX_LEN = 200
// "第N步"须跟标点、行首编号排除小数(如 23.5),且文本须多行(单行短句不可能是步骤清单)
const STEP_SIGNAL = /第[一二三四五六七八九十]步[：:，,]|解法[一二三][：:]|^[ \t]*\d+[、)]|^[ \t]*\d+\.(?!\d)/m
const SUMMARY_HEIGHT_CAP = 10   // 同类实体最多列 10 条,防刷屏

function checkSummaryHeight(g: LoadedGraph, report: LintReport): void {
  const hits = new Map<string, { id: string; message: string }[]>()
  for (const e of g.entities) {
    let text: string | undefined
    let field: string
    if (e.type === 'Concept') { text = (e as { explanation?: string }).explanation; field = 'explanation' }
    else continue
    if (!text) continue
    const tooLong = text.length > SUMMARY_MAX_LEN
    const hasSteps = /\n/.test(text) && STEP_SIGNAL.test(text)
    if (!tooLong && !hasSteps) continue
    const reason = tooLong ? `长度 ${text.length}` : '含步骤化信号'
    const arr = hits.get(e.type) ?? []
    arr.push({ id: e.id, message: `${e.id}: ${field} 疑似正文越界(${reason})——正文应归章节区块（v4）` })
    hits.set(e.type, arr)
  }
  for (const [type, arr] of hits) {
    for (const h of arr.slice(0, SUMMARY_HEIGHT_CAP)) {
      report.warnings.push(finding('summary-height', 'warning', h.message, h.id))
    }
    if (arr.length > SUMMARY_HEIGHT_CAP) {
      report.warnings.push(finding('summary-height', 'warning', `${type}: …等共 ${arr.length} 条 summary-height 告警`))
    }
  }
}

// rule 13 confidence: 带 confidence 且 < 0.7 的实体需人工审核,只作 informational warning
// 政策见 skills/00-META.md §7;存量实体无 confidence 视为未评分,不报
const CONFIDENCE_THRESHOLD = 0.7
const CONFIDENCE_CAP = 10   // 同类实体最多列 10 条,防刷屏

function checkConfidence(g: LoadedGraph, report: LintReport): void {
  const hits = new Map<string, { id: string; message: string }[]>()
  for (const e of g.entities) {
    const conf = (e as { confidence?: number }).confidence
    if (conf === undefined || conf >= CONFIDENCE_THRESHOLD) continue
    const arr = hits.get(e.type) ?? []
    arr.push({ id: e.id, message: `${e.id}: confidence ${conf} < 0.7,需人工审核` })
    hits.set(e.type, arr)
  }
  for (const [type, arr] of hits) {
    for (const h of arr.slice(0, CONFIDENCE_CAP)) {
      report.warnings.push(finding('confidence', 'warning', h.message, h.id))
    }
    if (arr.length > CONFIDENCE_CAP) {
      report.warnings.push(finding('confidence', 'warning', `${type}: …等共 ${arr.length} 条 confidence 告警`))
    }
  }
}

// rule 14 prerequisite-downstream: 下游混入边（to 名字包含 from 名字且更长，方向反了）。
// 语义上 B 名字含 A 作子串时 A 更基础、A 才是先修。error 级（方向正确性）。
// 挂起边豁免：与语义型③纠缠、反转会成环的边暂不报（见 先修方向判据修订（2026-08） 阶段 2），
// 由 suspended_edges.json 清单标记，否则 lint 基线被自己染红。
function checkPrerequisiteDownstream(g: LoadedGraph, report: LintReport, suspended?: Set<string>): void {
  const nameOf = (id: string) => id.split(':').slice(2).join(':')
  const subjOf = (id: string) => id.split(':')[1] ?? ''
  for (const r of g.relations) {
    if (r.type !== 'prerequisite') continue
    if (subjOf(r.from) !== subjOf(r.to)) continue
    const fn = nameOf(r.from)
    const tn = nameOf(r.to)
    if (!(fn && tn && tn.includes(fn) && tn.length > fn.length)) continue
    if (suspended?.has(`${r.from}|${r.to}`)) continue // 挂起边（先修方向判据修订（2026-08） 阶段 2）跳过
    report.errors.push(finding('prerequisite-downstream', 'error', `prerequisite 方向反了（to 是 from 的下游概念）`, `${r.from} → ${r.to}`))
  }
}

// rule 15 extension-provenance: 扩展知识必须自报家门,且与 id 前缀互相锁定。
// 两个方向都查,单向会留后门:只查前缀则可用 origin: extension 混进普通 id;
// 只查 origin 则可给 EXT- 教材写 origin: textbook。互锁后二者必须同时说谎才骗得过。
// source 对扩展知识是必填——第三方知识不记出处就无法追溯与撤回。
const EXT_PREFIX = 'EXT-'
function checkExtensionProvenance(g: LoadedGraph, report: LintReport): void {
  for (const e of g.entities) {
    if (e.type !== 'Textbook') continue
    const tb = e as { id: string; origin?: string; source?: string }
    const prefixed = tb.id.startsWith(EXT_PREFIX)
    const isExt = tb.origin === 'extension'
    if (prefixed && !isExt)
      report.errors.push(finding('extension-provenance', 'error', `id 以 ${EXT_PREFIX} 开头的虚拟教材必须声明 origin: extension,实际 ${tb.origin ?? '(缺失)'}`, tb.id))
    if (isExt && !prefixed)
      report.errors.push(finding('extension-provenance', 'error', `origin: extension 的教材 id 必须以 ${EXT_PREFIX} 开头`, tb.id))
    if (isExt && !tb.source)
      report.errors.push(finding('extension-provenance', 'error', `扩展知识必须在书级 front-matter 记 source（来源出处）`, tb.id))
    if (!isExt && tb.source)
      report.errors.push(finding('extension-provenance', 'error', `原始教材不应有 source（来源即教材本身,由 publisher/standardEdition 表达）`, tb.id))
  }
}

// rule 16 book-frontmatter-schema: 书级 index.md 的 front-matter 目前没有任何 schema 校验——
// deriveStructure 对 textbookId 缺失 / chapters 非数组是静默 continue（load.ts «未回填 chapters 的教材跳过»），
// 于是 chapters 键打错一个字母就会让整本书从图谱里消失，而 lint/build 全绿。此规则堵这个洞。
// 第 5 项「源文件数 == Textbook 节点数」是兜底不变量：逐字段校验只能挡住想得到的错法，不变量能挡住想不到的。
// subject 取值曾中英混用（43 本里 16 本用 Math/Politics 之类），按学科过滤会静默漏书而不报错（学科取值口径统一（2026-09））。
// 归一为中文后加此约束，否则下批摄入还会混进来。刻意写死而不从 concepts/*.yaml 文件名派生：
// 新学科第一本书入库时该目录可能还没有概念文件，派生会把合法的书判红。
const SUBJECTS = new Set(['语文', '数学', '英语', '物理', '化学', '生物', '历史', '地理', '道德与法治', '科学'])
const CHAPTER_ID_RE = /^C\d+$/
const SECTION_ID_RE = /^S\w+$/
interface FmChapter { id?: unknown; title?: unknown; order?: unknown; sections?: unknown }
// rule 21 book-index-required: 书级 index.md 缺失时 deriveStructure 静默跳过整本书，rule 16 也看不见它
// （2026-10-01 小学 56 本即如此：正文全在、图谱 0 节点、lint/build 全绿）。以 chapters/ 目录的存在为「这是一本书」的证据。
export function checkBookIndexRequired(g: LoadedGraph, report: LintReport): void {
  const root = resolve(g.rootDir)
  for (const dir of globSync(resolve(root, 'content/**/chapters')).sort()) {
    const book = dirname(dir)
    if (!existsSync(resolve(book, 'index.md'))) {
      report.errors.push(finding('book-index-required', 'error',
        '有 chapters/ 却没有书级 index.md：deriveStructure 会把整本书静默跳过', book.slice(root.length + 1)))
    }
  }
}

function checkBookFrontmatter(g: LoadedGraph, report: LintReport): void {
  const files = globSync(resolve(g.rootDir, 'content/**/index.md')).filter(p => !p.includes('/chapters/')).sort()
  const declared = new Set<string>()
  for (const file of files) {
    const ref = file.slice(resolve(g.rootDir).length + 1)
    const err = (msg: string): void => { report.errors.push(finding('book-frontmatter-schema', 'error', msg, ref)) }
    let fm: Record<string, unknown>
    try {
      fm = parseSupplement(readFileSync(file, 'utf8')).frontmatter
    } catch (e) {
      err(`书级 index.md front-matter 解析失败：${(e as Error).message}`)
      continue
    }
    const tbId = fm.textbookId
    if (typeof tbId !== 'string' || tbId === '') {
      err('缺 front-matter textbookId')
      continue
    }
    declared.add(tbId)
    if (fm.origin !== 'textbook' && fm.origin !== 'extension') {
      err(`origin 必须是 textbook 或 extension，实际 ${String(fm.origin ?? '(缺失)')}`)
    }
    if (typeof fm.subject !== 'string' || !SUBJECTS.has(fm.subject)) {
      err(`subject 必须是 ${[...SUBJECTS].join('/')} 之一，实际 ${String(fm.subject ?? '(缺失)')}`)
    }
    const chapters = fm.chapters
    if (!Array.isArray(chapters) || chapters.length === 0) {
      err(`chapters 必须是非空数组，实际 ${Array.isArray(chapters) ? '空数组' : typeof chapters}`)
      continue
    }
    for (const raw of chapters as FmChapter[]) {
      const cid = raw?.id
      if (typeof cid !== 'string' || !CHAPTER_ID_RE.test(cid)) {
        err(`章 id 必须是 C<n> 形态，实际 ${String(cid ?? '(缺失)')}`)
        continue
      }
      if (typeof raw.title !== 'string' || typeof raw.order !== 'number') {
        err(`${cid} 缺 title 或 order`)
      }
      const sections = raw.sections
      if (sections === undefined) continue
      if (!Array.isArray(sections)) {
        err(`${cid}.sections 必须是数组，实际 ${typeof sections}`)
        continue
      }
      for (const s of sections as FmChapter[]) {
        const sid = s?.id
        if (typeof sid !== 'string' || !SECTION_ID_RE.test(sid)) {
          err(`${cid} 下节 id 必须是 S<n> 形态，实际 ${String(sid ?? '(缺失)')}`)
          continue
        }
        if (typeof s.title !== 'string' || typeof s.order !== 'number') {
          err(`${cid}-${sid} 缺 title 或 order`)
        }
      }
    }
  }
  // 不变量：每份书级 index.md 都应派生出一个 Textbook 节点，反之亦然
  const nodes = new Set(g.entities.filter(e => e.type === 'Textbook').map(e => e.id))
  for (const id of declared) {
    if (!nodes.has(id)) {
      report.errors.push(finding('book-frontmatter-schema', 'error', `书级 index.md 声明了 ${id}，但图谱里没有对应 Textbook 节点（deriveStructure 把它静默跳过了）`, id))
    }
  }
  for (const id of nodes) {
    if (!declared.has(id)) {
      report.errors.push(finding('book-frontmatter-schema', 'error', `图谱里有 Textbook 节点 ${id}，但 content/ 下找不到声明它的书级 index.md`, id))
    }
  }
}

// rule 17 pageRange-required: pageRange 在 schema 里对扩展知识放宽为可选（扩展知识无纸质页码），
// 原始教材的必填性改由此处强制——严格程度一分不减，只是从 zod 挪到了 lint。
//
// 唯一的豁免口：章正文没有 `<!-- page N -->` 标记时（Chapter.bodyHasPageMarkers === false），
// 节页码根本无源可取。此时要么让节缺页码，要么按字数摊派编一个——后者正是 页码语义裁决（2026-08）
// 页码语义那一课要避免的错法（「看着对但其实是编的」比缺失更坏，因为它不可辨认）。
// 故豁免的是「缺失」，不是「随便填」：同一章里若已有节带上了页码，说明那句「无页标记」
// 的声明与数据自相矛盾，反过来报错。章本身的 pageRange 一律必填，不受豁免。
function checkPageRangeRequired(g: LoadedGraph, report: LintReport): void {
  const origin = new Map<string, string>()
  const noMarkers = new Set<string>()
  for (const e of g.entities) {
    if (e.type === 'Textbook') origin.set(e.id, (e as { origin?: string }).origin ?? '')
    if (e.type === 'Chapter' && (e as { bodyHasPageMarkers?: boolean }).bodyHasPageMarkers === false) {
      noMarkers.add(e.id)
    }
  }
  for (const e of g.entities) {
    if (e.type !== 'Chapter' && e.type !== 'Section') continue
    const node = e as unknown as { id: string; chapterId?: string; textbookId: string; pageRange?: unknown }
    if (origin.get(node.textbookId) !== 'textbook') continue
    const exempt = e.type === 'Section' && node.chapterId !== undefined && noMarkers.has(node.chapterId)
    if (node.pageRange === undefined) {
      if (exempt) continue
      report.errors.push(finding('pageRange-required', 'error', `origin: textbook 的 ${e.type} 必须有 pageRange`, node.id))
    } else if (exempt) {
      report.errors.push(finding('pageRange-required', 'error',
        `所属章声明 bodyHasPageMarkers: false（正文无页标记），此节却有 pageRange——页码无源可取，不得填`, node.id))
    }
  }
}

// rule 18 pageRange-bounds: 页码不得越出书本身。
//
// 语义（2026-10 实测确认）：pageRange 是**印刷页码**，PDF/页图页序 = 印刷页码 + imageOffset。
// 书级 totalPages 必须是 **PDF 页数**（与 source_data/<book>/metadata.json 一致），
// 于是合法条件就是 pageRange[1] + imageOffset <= totalPages。
//
// 章与节都校验。章级的坑与节不同：章的 pageRange 要覆盖「单元小结/练习/阅读实践/
// 写作/整本书阅读」这些**没有对应节**的板块，早年有一批章直接把上界写成了 PDF 总页数
// （SK-8-1-Physics C5 121-158、PEP-7-1-Biology C9 122-146 等 4 册），
// 另有 28 章把后记/封底/空白页算了进来——均已按 PDF 实页核实修正。
//
// totalPages 曾经各册语义不一（有的记 PDF 页数、有的记印刷页数），已按 metadata.json 统一；
// 漂移由 tools/kg/scripts/check_pages.py 的一致性检查拦截。
function checkPageRangeBounds(g: LoadedGraph, report: LintReport): void {
  const books = new Map<string, { totalPages?: number; offset: number }>()
  for (const e of g.entities) {
    if (e.type !== 'Textbook') continue
    const t = e as { totalPages?: number; imageOffset?: number }
    books.set(e.id, { totalPages: t.totalPages, offset: t.imageOffset ?? 0 })
  }
  for (const e of g.entities) {
    if (e.type !== 'Chapter' && e.type !== 'Section') continue
    const node = e as { id: string; textbookId: string; pageRange?: [number, number] }
    const r = node.pageRange
    if (!r) continue
    const b = books.get(node.textbookId)
    if (!b?.totalPages) continue
    if (r[0] < 1 || r[1] < r[0]) {
      report.errors.push(finding('pageRange-bounds', 'error', `页码区间非法 [${r[0]}, ${r[1]}]`, node.id))
      continue
    }
    const lastPdfPage = r[1] + b.offset
    if (lastPdfPage > b.totalPages) {
      report.errors.push(finding('pageRange-bounds', 'error',
        `页码越界：印刷 p.${r[1]} + imageOffset ${b.offset} = 第 ${lastPdfPage} 页，超过全书 ${b.totalPages} 页`,
        node.id))
    }
  }
}

// rule 19 section-toc-agree: 已重切书（outlineSource: catalog-toc）节标题须与目录快照宽容一致（warning，灰度）
// （原 rule 18 duplicate-exercise-body 随 2026-09-27 刷题层移除删除，rule 19 编号保持不变）
export function checkSectionTocAgree(g: LoadedGraph, report: LintReport, snapPathOverride?: string): void {
  const snapPath = snapPathOverride ?? resolve(g.rootDir, 'tools/kg/state/curriculum_toc.json')
  if (!existsSync(snapPath)) return // 快照不存在整体跳过（不构成硬依赖，设计 §5.6）
  const snap = JSON.parse(readFileSync(snapPath, 'utf8')) as { books: Array<{ id: string; chapters: Array<{ id: string; sections: Array<{ id: string; title: string }> }> }> }
  const pgTitleById = new Map<string, string>()
  for (const b of snap.books) for (const c of b.chapters) for (const s of c.sections) pgTitleById.set(s.id, s.title)
  const paths = globSync(resolve(g.rootDir, 'content/**/index.md')).filter((p) => !p.includes('/chapters/'))
  for (const file of paths) {
    const fm = parseSupplement(readFileSync(file, 'utf8')).frontmatter as Record<string, unknown>
    if (fm?.outlineSource !== 'catalog-toc') continue // 未标记书跳过（灰度）
    for (const ch of (fm.chapters as Array<{ id: string; sections?: Array<{ id: string; title: string }> }>)) {
      for (const s of ch.sections ?? []) {
        const fullId = `${fm.textbookId}-${ch.id}-${s.id}`
        const pg = pgTitleById.get(fullId)
        if (pg === undefined) {
          report.warnings.push(finding('section-toc-agree', 'warning', `已重切书的节不在快照中：${fullId}`, fullId))
        } else if (normTitle(pg) !== normTitle(s.title)) {
          report.warnings.push(finding('section-toc-agree', 'warning', `节标题与目录快照不一致：图谱「${s.title}」vs 快照「${pg}」`, fullId))
        }
      }
    }
  }
}

export function lint(g: LoadedGraph, suspended?: Set<string>): LintReport {
  const report: LintReport = { errors: [], warnings: [] }
  checkSchema(g, report)
  checkOntologyDrift(g, report)
  checkIdUniqueness(g, report)
  checkRelationEndpoints(g, report)
  checkReferentialIntegrity(g, report)
  checkCycle(g, report)
  checkOrphan(g, report)
  checkSourceRef(g, report)
  checkLayerPlacement(g, report)
  checkSummaryHeight(g, report)
  checkConfidence(g, report)
  checkPrerequisiteDownstream(g, report, suspended)
  checkExtensionProvenance(g, report)
  checkBookFrontmatter(g, report)
  checkBookIndexRequired(g, report)
  checkPageRangeRequired(g, report)
  checkPageRangeBounds(g, report)
  checkSectionTocAgree(g, report)
  checkSectionProseMin(g, report)
  checkSectionConceptMin(g, report)
  checkSectionConceptMinJunior(g, report)
  checkCoveredByAnchor(g, report)
  checkPrereqReviewTier(g, report)
  return report
}

// rule 20 section-prose-min: 节正文最短门禁——防「重切丢正文」类事故静默通过（2026-09-27 空壳事故，
// 81 节正文被批次 apply 重切清空而 lint 全绿）。口径与巡检一致：去 frontmatter/标题/表格/插图区后的正文字符。
// ⚠ 豁免清单 = 存量已知缺口（git 全历史即无正文，非本次事故），待用户裁决补 OCR/删节后清零删行。
const SECTION_PROSE_MIN = 100
const SECTION_PROSE_EXEMPT = new Set([
  // PEP-7-2-Politics-C3-S16 已于 2026-09-28 校准回填（shingle 0.9232），移出豁免
  'content/七年级/下册/地理/ZTB-7-2-Geography/chapters/C9/sections/S1.md',
  'content/八年级/下册/生物/PEP-8-2-Biology/chapters/C5/sections/S2.md',
  'content/七年级/下册/英语/PEP-7-2-English/chapters/C14/sections/S1.md',
  // 2026-10-17 PEP-8-2-English C8-C12 结构重构：C12/S3 不规则动词表为纯表节（p.137-141 三列动词表按页图回填，无散文正文）
  'content/八年级/下册/英语/PEP-8-2-English/chapters/C12/sections/S3.md',
])
// 小学内容判例（2026-10-01）：两类合法形态不计 <100 门禁——
// ①纯表节（词语表/写字表/词汇表等，正文口径按设计跳过表格行 → 计 0）②忠实短页（整理与复习/学期回顾类版面）
const SECTION_PROSE_EXEMPT_PRIMARY = new Set([
  'content/一年级/上册/科学/ES-1-1-Science/chapters/C1/sections/S7.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C1/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C1/sections/S2.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C1/sections/S3.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C1/sections/S4.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C10/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C11/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C12/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C13/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C2/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C2/sections/S3.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C2/sections/S4.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C2/sections/S7.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C3/sections/S2.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C7/sections/S1.md',
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C9/sections/S5.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C1/sections/S7.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C10/sections/S1.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C10/sections/S2.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C10/sections/S3.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C10/sections/S4.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C11/sections/S1.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C7/sections/S6.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C9/sections/S1.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C9/sections/S2.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C9/sections/S3.md',
  'content/一年级/下册/语文/PEP-1-2-Chinese/chapters/C9/sections/S4.md',
  'content/三年级/上册/数学/BSDU-3-1-Math/chapters/C10/sections/S3.md',
  'content/三年级/下册/数学/BSDU-3-2-Math/chapters/C2/sections/S6.md',
  'content/三年级/下册/英语/PEP-3-2-English/chapters/C10/sections/S1.md',
  'content/三年级/下册/英语/PEP-3-2-English/chapters/C9/sections/S1.md',
  // 纯表节判例（2026-10-15）：Appendix 8 语音表×3（批3 后记错插块删除后仅存语音表， canonical pp70-73）
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S6.md',
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S2.md',
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S7.md',
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C3/sections/S5.md',
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C4/sections/S6.md',
  'content/二年级/下册/语文/PEP-2-2-Chinese/chapters/C10/sections/S1.md',
  'content/二年级/下册/语文/PEP-2-2-Chinese/chapters/C11/sections/S1.md',
  'content/二年级/下册/语文/PEP-2-2-Chinese/chapters/C3/sections/S6.md',
  'content/二年级/下册/语文/PEP-2-2-Chinese/chapters/C7/sections/S6.md',
  'content/二年级/下册/语文/PEP-2-2-Chinese/chapters/C9/sections/S1.md',
  'content/五年级/下册/数学/BSDU-5-2-Math/chapters/C11/sections/S3.md',
  'content/五年级/下册/数学/BSDU-5-2-Math/chapters/C11/sections/S4.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C10/sections/S1.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C10/sections/S2.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C12/sections/S1.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C9/sections/S1.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C9/sections/S2.md',
  'content/六年级/上册/语文/PEP-6-1-Chinese/chapters/C9/sections/S1.md',
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S2.md',
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S5.md',
  'content/六年级/下册/语文/PEP-6-2-Chinese/chapters/C7/sections/S5.md',
  'content/六年级/下册/语文/PEP-6-2-Chinese/chapters/C7/sections/S6.md',
  'content/四年级/下册/数学/BSDU-4-2-Math/chapters/C9/sections/S3.md',
  'content/四年级/下册/数学/BSDU-4-2-Math/chapters/C9/sections/S4.md',
// 2026-10-01 P0 无节章切分（D5）新增：附录纯表/短页
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C10/sections/S1.md',
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C10/sections/S2.md',
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C11/sections/S1.md',
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C13/sections/S1.md',
// 2026-10-04 PEP-7-1-English 附录回填：C18 参考词表为纯表节（词表按页图回填，无散文正文）
  'content/七年级/上册/英语/PEP-7-1-English/chapters/C18/sections/S1.md',
// 2026-10-04 PEP-7-1-English 附录回填：C15/C16/C17 词表同为纯表节（p.N 反查单元/字母序回填，无散文正文）
  'content/七年级/上册/英语/PEP-7-1-English/chapters/C15/sections/S1.md',
  'content/七年级/上册/英语/PEP-7-1-English/chapters/C16/sections/S1.md',
  'content/七年级/上册/英语/PEP-7-1-English/chapters/C17/sections/S1.md',
])
// v4 白名单区块为附加内容，不计入教材正文口径（与 verify_prose.section_prose 一致）
const PROSE_BLOCK_WHITELIST = new Set(['插图', '解题模型', '笔记', '总结', '生字', '单词', '短语', '句子'])

export function checkSectionProseMin(g: LoadedGraph, report: LintReport): void {
  const paths = globSync(resolve(g.rootDir, 'content/**/chapters/*/sections/S*.md'))
  for (const file of paths.sort()) {
    const rel = file.slice(g.rootDir.length + 1)
    if (SECTION_PROSE_EXEMPT.has(rel) || SECTION_PROSE_EXEMPT_PRIMARY.has(rel)) continue
    let text = readFileSync(file, 'utf8').replace(/^---[\s\S]*?\n---\n/, '')
    let inBlock = false
    let chars = 0
    for (const line of text.split('\n')) {
      if (line.startsWith('## ')) {
        inBlock = PROSE_BLOCK_WHITELIST.has(line.trim().slice(3).trim())
        continue
      }
      if (line.startsWith('#') || line.startsWith('|') || inBlock) continue
      chars += line.replace(/ /g, '').length
    }
    if (chars < SECTION_PROSE_MIN) {
      report.errors.push(finding('section-prose-min', 'error',
        `节正文 ${chars} 字符 < ${SECTION_PROSE_MIN}（空壳/占位，正文缺失或未派生）`, rel))
    }
  }
}

// rule 22 section-concept-min（P1.2）：小学（1–6 年级）有正文的节至少被 1 个概念 covered_by。
// 豁免 = 节正文门禁的小学豁免清单（纯表/短页）+ 后记节（spec §5 O4 默认：保留为节、不计门禁）。
// P1.2 收口后为 error：小学有正文节必须贡献概念，豁免清零（评审逐条裁决）
const POSTSCRIPT_SECTIONS = new Set([
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S9.md',
  'content/三年级/上册/数学/BSDU-3-1-Math/chapters/C12/sections/S6.md',
  'content/三年级/下册/数学/BSDU-3-2-Math/chapters/C11/sections/S6.md',
  'content/五年级/上册/数学/BSDU-5-1-Math/chapters/C12/sections/S6.md',
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C13/sections/S6.md',
  'content/六年级/上册/道德与法治/PEP-6-1-Politics/chapters/C4/sections/S3.md',
  'content/六年级/下册/语文/PEP-6-2-Chinese/chapters/C9/sections/S2.md',
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C12/sections/S2.md',
  'content/三年级/下册/英语/PEP-3-2-English/chapters/C12/sections/S2.md',
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C12/sections/S3.md',
])

// rule 22 残留裁决豁免（P1.2 Task 8，评审逐条通过）：无可抽知识点的表格/附录/活动页
const SECTION_CONCEPT_EXEMPT = new Set<string>([
  // 字词表（70）
  'content/三年级/上册/语文/PEP-3-1-Chinese/chapters/C10/sections/S1.md', // 写字表
  'content/三年级/上册/语文/PEP-3-1-Chinese/chapters/C11/sections/S1.md', // 词语表
  'content/三年级/下册/语文/PEP-3-2-Chinese/chapters/C10/sections/S1.md', // 写字表
  'content/三年级/下册/语文/PEP-3-2-Chinese/chapters/C11/sections/S1.md', // 词语表
  'content/三年级/下册/语文/PEP-3-2-Chinese/chapters/C9/sections/S1.md', // 识字表
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S1.md', // 写字表
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S2.md', // 第二单元·识字
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S3.md', // 第三单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S4.md', // 第四单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S5.md', // 第五单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S6.md', // 第六单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S7.md', // 第七单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C10/sections/S8.md', // 第八单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S1.md', // 词语表
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S3.md', // 第三单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S4.md', // 第四单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S5.md', // 第五单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S6.md', // 第六单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C11/sections/S8.md', // 第八单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S1.md', // 识字表
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S2.md', // 第二单元·识字
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S3.md', // 第三单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S4.md', // 第四单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S5.md', // 第五单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S6.md', // 第六单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S7.md', // 第七单元·阅读
  'content/二年级/上册/语文/PEP-2-1-Chinese/chapters/C9/sections/S8.md', // 第八单元·阅读
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C10/sections/S1.md', // Appendix 3 Vocabulary 词汇表
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C9/sections/S1.md', // Unit 1
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C9/sections/S2.md', // Unit 3
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C9/sections/S3.md', // Unit 6
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C10/sections/S1.md', // 写字表（第 1 课起）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C10/sections/S2.md', // 写字表（第 18 课起）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C11/sections/S1.md', // 词语表（第 1 课起）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C11/sections/S2.md', // 7（续）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C11/sections/S3.md', // 语文园地
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C9/sections/S1.md', // 识字表（第 1 课起）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C9/sections/S2.md', // 识字表（第 10 课起）
  'content/五年级/上册/语文/PEP-5-1-Chinese/chapters/C9/sections/S3.md', // 语文园地
  'content/五年级/下册/英语/PEP-5-2-English/chapters/C10/sections/S1.md', // Words in each unit
  'content/五年级/下册/英语/PEP-5-2-English/chapters/C11/sections/S1.md', // Vocabulary 词汇表
  'content/五年级/下册/语文/PEP-5-2-Chinese/chapters/C10/sections/S1.md', // 写字表（第 1 课起）
  'content/五年级/下册/语文/PEP-5-2-Chinese/chapters/C11/sections/S1.md', // 词语表（第 2 课起）
  'content/五年级/下册/语文/PEP-5-2-Chinese/chapters/C9/sections/S1.md', // 识字表（第 1 课起）
  'content/六年级/上册/语文/PEP-6-1-Chinese/chapters/C10/sections/S1.md', // 词语表
  'content/六年级/下册/语文/PEP-6-2-Chinese/chapters/C8/sections/S1.md', // 写字表
  'content/六年级/下册/语文/PEP-6-2-Chinese/chapters/C9/sections/S1.md', // 词语表
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C10/sections/S1.md', // Appendix 3 Vocabulary（词汇表）
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C9/sections/S1.md', // Unit 1
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C9/sections/S2.md', // Unit 4
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C9/sections/S3.md', // Unit 6
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C10/sections/S1.md', // 写字表（第 1 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C10/sections/S2.md', // 写字表（第 16 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C11/sections/S1.md', // 词语表（第 1 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C11/sections/S2.md', // 词语表（第 11 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C11/sections/S3.md', // 词语表（第 21 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C9/sections/S1.md', // 识字表（第 1 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C9/sections/S2.md', // 识字表（第 14 课起）
  'content/四年级/上册/语文/PEP-4-1-Chinese/chapters/C9/sections/S3.md', // 识字表（第 24 课起）
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C10/sections/S1.md', // Appendix 3 Vocabulary（词汇表）
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C9/sections/S1.md', // Unit 1
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C9/sections/S2.md', // Unit 3
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C9/sections/S3.md', // Unit 6
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C10/sections/S1.md', // 写字表
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C10/sections/S2.md', // 写字表（第 18 课起）
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C11/sections/S1.md', // 词语表（第 2 课起）
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C11/sections/S2.md', // 词语表（第 11 课起）
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C9/sections/S1.md', // 识字表
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C9/sections/S2.md', // 识字表（第 11 课起）
  'content/四年级/下册/语文/PEP-4-2-Chinese/chapters/C9/sections/S3.md', // 20（续）
  // 英语附录（歌曲/常用表达/谚语/短剧/语音汇总）与复习单元歌谣/看图说话页（29）
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C12/sections/S1.md', // Unit 1
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C12/sections/S2.md', // Unit 4
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C8/sections/S1.md', // Unit 1 Finger family song
  'content/三年级/上册/英语/PEP-3-1-English/chapters/C8/sections/S2.md', // Unit 4 Plants and us
  'content/三年级/下册/英语/PEP-3-2-English/chapters/C11/sections/S1.md', // Appendix 4 Useful expressions
  'content/三年级/下册/英语/PEP-3-2-English/chapters/C8/sections/S1.md', // Songs 歌曲
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C11/sections/S1.md', // Unit 1
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C11/sections/S2.md', // Unit 4
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C7/sections/S2.md', // Look, think and talk
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C8/sections/S1.md', // Unit 1 My friends
  'content/五年级/上册/英语/PEP-5-1-English/chapters/C8/sections/S2.md', // Unit 4 Good habits
  'content/五年级/下册/英语/PEP-5-2-English/chapters/C12/sections/S1.md', // Useful expressions 常用表达法
  'content/五年级/下册/英语/PEP-5-2-English/chapters/C13/sections/S1.md', // Proverbs 谚语
  'content/五年级/下册/英语/PEP-5-2-English/chapters/C9/sections/S1.md', // Songs in each unit
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C11/sections/S1.md', // Unit 1
  'content/六年级/上册/英语/PEP-6-1-English/chapters/C8/sections/S1.md', // Songs（歌曲）
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S1.md', // Appendix 1 Songs in each unit（各单元歌曲）
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S3.md', // Appendix 4 Useful expressions（常用表达法）
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S4.md', // Appendix 6 Short plays（短剧）
  'content/六年级/下册/英语/PEP-6-2-English/chapters/C6/sections/S6.md', // Appendix 8 English pronunciation patterns（语音）
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C11/sections/S1.md', // Unit 1
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C11/sections/S2.md', // Unit 5
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C7/sections/S4.md', // Listen and chant.
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C8/sections/S1.md', // Unit 1 Helping at home
  'content/四年级/上册/英语/PEP-4-1-English/chapters/C8/sections/S2.md', // Unit 5 The weather and us
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C11/sections/S1.md', // Unit 1
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C11/sections/S2.md', // Unit 6
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C8/sections/S1.md', // Unit 1
  'content/四年级/下册/英语/PEP-4-2-English/chapters/C8/sections/S2.md', // Unit 5
  // 附页（操作材料）（5）
  'content/三年级/上册/数学/BSDU-3-1-Math/chapters/C12/sections/S5.md', // 附页
  'content/三年级/下册/数学/BSDU-3-2-Math/chapters/C11/sections/S5.md', // 附页
  'content/二年级/上册/数学/BSDU-2-1-Math/chapters/C12/sections/S4.md', // 附页
  'content/五年级/上册/数学/BSDU-5-1-Math/chapters/C12/sections/S5.md', // 附页
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C13/sections/S5.md', // 附页
  // 综合实践/复习自评页（7）
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C12/sections/S1.md', // 综合实践：制订营养食谱
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C12/sections/S2.md', // 调查营养要求
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C12/sections/S5.md', // 一日食谱交流会
  'content/六年级/上册/数学/BSDU-6-1-Math/chapters/C4/sections/S1.md', // 综合实践：制订节水方案
  'content/六年级/下册/数学/BSDU-6-2-Math/chapters/C7/sections/S14.md', // 本学期你学到了什么
  'content/四年级/上册/数学/BSDU-4-1-Math/chapters/C11/sections/S4.md', // 研究分享会
  'content/四年级/下册/数学/BSDU-4-2-Math/chapters/C4/sections/S2.md', // 我的成长足迹
  // 一年级入学活动页、共读页与只含生字的课文（15）
  'content/一年级/上册/数学/BSDU-1-1-Math/chapters/C1/sections/S2.md', // 认识 · 新同学
  'content/一年级/上册/数学/BSDU-1-1-Math/chapters/C1/sections/S4.md', // 好玩的游戏
  'content/一年级/上册/数学/BSDU-1-1-Math/chapters/C1/sections/S5.md', // 收获的季节
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C2/sections/S8.md', // 快乐读书吧：读书真快乐
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C5/sections/S7.md', // 和大人一起读：小鸟念书
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C6/sections/S2.md', // 课文 2　江南
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C6/sections/S3.md', // 课文 3　雪地里的小画家
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C6/sections/S4.md', // 课文 4 四季
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C6/sections/S7.md', // 和大人一起读：拔萝卜
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C7/sections/S3.md', // 识字 7　小书包
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C7/sections/S4.md', // 识字 8　升国旗
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C7/sections/S6.md', // 和大人一起读：小松鼠找花生
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C8/sections/S3.md', // 课文 7 两件宝
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C8/sections/S6.md', // 和大人一起读：猴子捞月亮
  'content/一年级/上册/语文/PEP-1-1-Chinese/chapters/C9/sections/S2.md', // 课文 9　乌鸦喝水
])

export function checkSectionConceptMin(g: LoadedGraph, report: LintReport): void {
  const grade = new Map<string, number>()
  for (const e of g.entities) {
    if (e.type === 'Textbook') grade.set(e.id, Number((e as { grade?: unknown }).grade))
  }
  const covered = new Set(g.relations.filter(r => r.type === 'covered_by').map(r => r.to))
  for (const e of g.entities) {
    if (e.type !== 'Section') continue
    const s = e as { id: string; textbookId: string; sourceRef?: string }
    const gr = grade.get(s.textbookId)
    if (gr === undefined || !(gr <= 6)) continue
    if (covered.has(s.id)) continue
    if (s.sourceRef && (SECTION_PROSE_EXEMPT_PRIMARY.has(s.sourceRef) || POSTSCRIPT_SECTIONS.has(s.sourceRef) || SECTION_CONCEPT_EXEMPT.has(s.sourceRef))) continue
    report.errors.push(finding('section-concept-min', 'error', '小学节未贡献任何概念（无 covered_by）', s.id))
  }
}

// rule 25 section-concept-min-junior（2026-10-25）：初中（7–9 年级）有正文的节必须有概念。
//
// 为什么加：rule 22 只覆盖小学，初中长期没有兜底。2026-10-25 实测 155 个初中节有正文却
// 零概念，其中 94 个是真内容节（「整式的加减」「光合作用」「远离违法犯罪」这类核心课）——
// 没人报错、也没人发现。补完 24 个概念后真内容节清零，遂立规防回归。
//
// 豁免按「章 + 节」双层判：结构类内容的章名（综合与实践/跨学科/主题活动）与节名
// （复习题/单元思考/附录/听力原文/词表/Project）都在豁免内。首版为 warning：
// 新书摄入时先暴露、不阻塞构建，模式稳定后再考虑升 error。
const SECTION_STRUCTURAL_TITLE =
  /复习|回顾|习题|练习|单元思考|^第[一二三四五六七八九十]+单元$|活动课|附录|后记|致谢|版权|图例|索引|听力原文|Listening|Pronunciation|Vocabulary|Reading\s*Plus|Project|Reflecting|Section\s*[A-Z]|主题[一二三四五六七八九十]|导言|序言|学期回顾|整理与复习|拓展阅读|阅读综合实践|综合实践项目|问题解决活动/
const SECTION_STRUCTURAL_CHAPTER = /综合与实践|综合实践|跨学科|主题学习|活动·探究|名著导读|整本书阅读/

export function checkSectionConceptMinJunior(g: LoadedGraph, report: LintReport): void {
  const grade = new Map<string, number>()
  for (const e of g.entities) {
    if (e.type === 'Textbook') grade.set(e.id, Number((e as { grade?: unknown }).grade))
  }
  const chapterTitle = new Map<string, string>()
  for (const e of g.entities) {
    if (e.type === 'Chapter') chapterTitle.set(e.id, String((e as { title?: unknown }).title ?? ''))
  }
  const covered = new Set(g.relations.filter(r => r.type === 'covered_by').map(r => r.to))
  for (const e of g.entities) {
    if (e.type !== 'Section') continue
    const s = e as { id: string; textbookId: string; chapterId?: string; title?: string; sourceRef?: string }
    const gr = grade.get(s.textbookId)
    if (gr === undefined || gr < 7) continue
    if (covered.has(s.id)) continue
    if (SECTION_STRUCTURAL_TITLE.test(s.title ?? '')) continue
    if (SECTION_STRUCTURAL_CHAPTER.test(chapterTitle.get(s.chapterId ?? '') ?? '')) continue
    if (s.sourceRef && (POSTSCRIPT_SECTIONS.has(s.sourceRef) || SECTION_CONCEPT_EXEMPT.has(s.sourceRef) || SECTION_PROSE_EXEMPT.has(s.sourceRef))) continue
    // 正文过短的归 rule 20 管，这里不重复报
    if (!s.sourceRef) continue
    const p = resolve(g.rootDir, s.sourceRef)
    if (!existsSync(p)) continue
    const text = readFileSync(p, 'utf8').replace(/^---[\s\S]*?\n---\n/, '')
    const body = text
      .split('\n')
      .filter(l => !l.startsWith('#') && !l.startsWith('|'))
      .join('')
      .replace(/\s+/g, '')
    if (body.length < SECTION_PROSE_MIN) continue
    report.warnings.push(
      finding('section-concept-min-junior', 'warning', '初中节有正文但未贡献任何概念（无 covered_by）', s.id),
    )
  }
}

// rule 23 covered-by-anchor（kg-repair L4 引用层门禁，2026-10-15 立；2026-10-25 语义重定）
//
// 立规初衷：治理重切/搬移后 covered_by 悬空漂移的静默污染（语文内容审计（2026-09） 批3 八下语文字表
// 搬家致 demonstrates 3 边悬挂的通用化）。原实现按「每条边的概念标题能否在所指节正文
// 逐字命中」计数，但 2026-10-25 全量审计（1,505 条）证明这个口径测的不是「边错」：
//   · 同书任何节都命中不了的占 92%——Concept 名多为概括句（「袁世凯窃取辛亥革命果实」），
//     正文用叙述表达，逐字锚定在结构上不可能成立；
//   · 真·挂错节只有个位数（已修 17 条，剩 7 条待 kg-review 逐条裁）。
// 继续逐条追这 1,500 条是假账：既修不完，又会把真信号（节正文缺失/错位）淹掉。
//
// 现行语义（两层，2026-10-25）：
//   ① **节级覆盖率**（可执行信号）：某节锚不上的概念 ≥5 且占该节可判定概念 ≥50%
//      → 该节正文很可能缺失/错位/纯表（如语文九下 C2/S1 55 个概念全部锚不上），
//      逐节告警并映射到 kg-review / delta 卡；
//   ② **零散未锚定**：不足阈值的不逐条告警，只出一条汇总——它们多是概括句标题，
//      不构成缺陷，避免 1,000+ 条噪声让真信号失效。
// 锚定判定三档：标题/别名逐字命中 → 关键词全中 → **节标题**（概念名=课文名/诗名/
// 专题名时，正文天然不会重复标题，节标题本身就是覆盖证据）。
const COVERED_BY_SECTION_MIN = 5
const COVERED_BY_SECTION_RATE = 0.5
/** 节级告警最多逐节列多少个，其余走汇总 */
const COVERED_BY_SECTION_CAP = 20

export function checkCoveredByAnchor(g: LoadedGraph, report: LintReport): void {
  // 英语整科豁免：Concept 标题是中文术语（「一般现在时」），节正文是英文原文，
  // 子串锚定在结构上不可能命中（实测 79%，加别名兜底仍 64%）；英语 covered_by 的
  // 漂移改用 demonstrates 侧巡检。
  const EXEMPT_SUBJECTS = new Set(['英语'])
  const probeOf = new Map<string, string[]>()
  const keywordsOf = new Map<string, string[] | null>()
  const subjectOf = new Map<string, string>()
  for (const e of g.entities) {
    if (e.type !== 'Concept') continue
    const c = e as { title?: string; aliases?: unknown; subject?: unknown }
    const probes = [c.title ?? c.id.split(':').pop() ?? '']
    if (Array.isArray(c.aliases)) probes.push(...(c.aliases as string[]))
    probeOf.set(e.id, probes.map((p) => p.replace(/\s+/g, '')).filter((p) => p.length >= 2))
    // 关键词兜底：标题按连接词切开，所有 ≥2 字段全部出现即视为锚定；单段标题不启用
    const segs = [...new Set((c.title ?? '').replace(/\s+/g, '').split(/的|与|和|、|，/).filter((s) => s.length >= 2))]
    keywordsOf.set(e.id, segs.length >= 2 ? segs : null)
    subjectOf.set(e.id, String(c.subject ?? ''))
  }
  const srcOf = new Map<string, string>()
  const secTitleOf = new Map<string, string>()
  for (const e of g.entities) {
    if (e.type !== 'Section') continue
    const s = e as { id: string; sourceRef?: string; title?: string }
    if (s.sourceRef) srcOf.set(s.id, s.sourceRef)
    secTitleOf.set(s.id, (s.title ?? '').replace(/\s+/g, ''))
  }
  const bodyCache = new Map<string, string | null>()
  const bodyOf = (rel: string): string | null => {
    const cached = bodyCache.get(rel)
    if (cached !== undefined) return cached
    const p = resolve(g.rootDir, rel)
    if (!existsSync(p)) {
      bodyCache.set(rel, null)
      return null
    }
    const text = readFileSync(p, 'utf8').replace(/^---[\s\S]*?\n---\n/, '')
    let inBlock = false
    const kept: string[] = []
    for (const line of text.split('\n')) {
      if (line.startsWith('## ')) {
        inBlock = true
        continue
      }
      if (line.startsWith('#') || line.startsWith('|') || inBlock) continue
      kept.push(line)
    }
    const body = kept.join('').replace(/\s+/g, '')
    bodyCache.set(rel, body)
    return body
  }

  const judgedBySec = new Map<string, number>()
  const missingBySec = new Map<string, string[]>()
  let exempted = 0
  for (const r of g.relations) {
    if (r.type !== 'covered_by') continue
    if (EXEMPT_SUBJECTS.has(subjectOf.get(r.from) ?? '')) {
      exempted++
      continue
    }
    const probes = probeOf.get(r.from) ?? []
    if (!probes.length) continue
    const rel = srcOf.get(r.to)
    if (!rel) continue
    if (SECTION_PROSE_EXEMPT_PRIMARY.has(rel) || SECTION_PROSE_EXEMPT.has(rel)) continue
    const body = bodyOf(rel)
    if (body === null || body.length < SECTION_PROSE_MIN) continue

    judgedBySec.set(r.to, (judgedBySec.get(r.to) ?? 0) + 1)
    if (probes.some((p) => body.includes(p))) continue
    const kws = keywordsOf.get(r.from)
    if (kws && kws.every((k) => body.includes(k))) continue
    // 第三档：节标题（课文名/诗名/专题名类）
    const secTitle = secTitleOf.get(r.to) ?? ''
    if (secTitle.includes(probes[0]) && probes[0].length >= 2) continue

    const arr = missingBySec.get(r.to) ?? []
    arr.push(probes[0])
    missingBySec.set(r.to, arr)
  }

  const concentrated: { sid: string; miss: string[]; total: number }[] = []
  // 零散未锚定按学段拆开统计：小学（1–6 年级）与初中形态不同——小学一节中位数 1 个概念，
  // 从无「整章压一节」；其未锚定几乎全是写作方法类元知识（「详略得当」「心理描写」），
  // 正文用叙述表达，不逐字出现属正常。混在一个数字里会让人误以为小学也有大问题。
  let sparsePrimary = 0
  let sparseOther = 0
  const PRIMARY_GRADE = /content\/[一二三四五六]年级\//
  for (const [sid, miss] of missingBySec) {
    const total = judgedBySec.get(sid) ?? miss.length
    if (miss.length >= COVERED_BY_SECTION_MIN && miss.length / total >= COVERED_BY_SECTION_RATE) {
      concentrated.push({ sid, miss, total })
    } else if (PRIMARY_GRADE.test(srcOf.get(sid) ?? '')) {
      sparsePrimary += miss.length
    } else {
      sparseOther += miss.length
    }
  }
  const sparse = sparsePrimary + sparseOther
  concentrated.sort((a, b) => b.miss.length - a.miss.length)

  for (const c of concentrated.slice(0, COVERED_BY_SECTION_CAP)) {
    const pct = Math.round((c.miss.length / c.total) * 100)
    report.warnings.push(
      finding(
        'covered-by-anchor',
        'warning',
        `节正文疑似缺失/错位：本节 ${c.total} 个概念中 ${c.miss.length} 个（${pct}%）在正文与节标题里都锚不上；` +
          `样例 ${c.miss.slice(0, 3).join('、')}——查正文是否缺失/串节（kg-review → delta 卡）`,
        c.sid,
      ),
    )
  }
  if (concentrated.length > COVERED_BY_SECTION_CAP) {
    report.warnings.push(
      finding(
        'covered-by-anchor',
        'warning',
        `…等共 ${concentrated.length} 个节覆盖率不足(${COVERED_BY_SECTION_RATE * 100}%)，完整清单见 delta 卡`,
        'covered_by',
      ),
    )
  }
  if (sparse > 0) {
    report.warnings.push(
      finding(
        'covered-by-anchor',
        'warning',
        `另有 ${sparse} 条零散未锚定（小学 ${sparsePrimary} / 初中 ${sparseOther}；` +
          `多为概括句与写作方法类元知识，正文用叙述表达，非缺陷，不逐条告警）；` +
          `英语 ${exempted} 条按学科豁免`,
        'covered_by',
      ),
    )
  }
}

// rule 24 prereq-review-tier（2026-10-25）：prerequisite 边必须显式声明复核档位。
// 背景：全库先修复核（2026-08） 只逐条判定过它结案时的 1614 条；其后的跨册先修批次只做过抽样
// （试点 5 本 40 条中 36 条正确），两档精度差一个量级。消费侧（learner 先修闭包）
// 只走 reviewed: audited，未标注即视为不可信——新边不标不会报错，只会静默从补救
// 路径里消失，症状是「本该有的一环不见了」，所以必须在建图期告警。
export function checkPrereqReviewTier(g: LoadedGraph, report: LintReport): void {
  const missing: string[] = []
  for (const r of g.relations) {
    if (r.type !== 'prerequisite') continue
    if (!r.reviewed) missing.push(`${r.from} → ${r.to}`)
  }
  if (!missing.length) return
  for (const m of missing.slice(0, 10)) {
    report.warnings.push(finding('prereq-review-tier', 'warning',
      `prerequisite 边缺 reviewed 档位（audited|sampled），消费侧会排除它：${m}`, 'prerequisite'))
  }
  if (missing.length > 10) {
    report.warnings.push(finding('prereq-review-tier', 'warning',
      `…等共 ${missing.length} 条 prerequisite 边缺 reviewed 档位`, 'prerequisite'))
  }
}

export function loadSuspendedEdges(root: string): Set<string> {
  const p = resolve(root, 'graph/suspended-prerequisites.json')
  if (!existsSync(p)) return new Set()
  let parsed: unknown
  try {
    parsed = JSON.parse(readFileSync(p, 'utf-8'))
  } catch (e) {
    // Fail Loud（CLAUDE.md 4.3）：清单存在但读不了/解析失败，绝不能伪装成空清单
    // （否则 rule 14 会把 93 条挂起边误报为方向错误，污染 lint 基线）。
    throw new Error(`suspended_edges.json 存在但解析失败（${p}）：${(e as Error).message}。请修复清单或删除该文件。`)
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`suspended_edges.json 格式错误（${p}）：期望 string[]，实际 ${typeof parsed}。`)
  }
  return new Set(parsed as string[])
}

function main(): void {
  const arg = process.argv.slice(2).find(a => !a.startsWith('-'))
  const root = resolve(arg ?? process.cwd())
  const g = loadGraph(root)
  const report = lint(g, loadSuspendedEdges(root))
  for (const f of report.errors) console.error(`  ✖ [error] ${f.rule}: ${f.message}${f.ref ? ` (${f.ref})` : ''}`)
  for (const f of report.warnings) console.warn(`  ⚠ [warn]  ${f.rule}: ${f.message}${f.ref ? ` (${f.ref})` : ''}`)
  console.log(`\n${report.errors.length} error(s), ${report.warnings.length} warning(s)`)
  if (report.errors.length > 0) process.exit(1)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
