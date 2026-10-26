// kg_ask.ts — 知识库「有界切片 / 闭包」后端原语（供 LLM 前置的 skill 调用）
//
// 设计定位：知识库是层级网状结构，LLM 应逐层下钻、只取所需切片，而非全量加载。
// 本脚本只做 LLM 在上下文里做不好的两件事：
//   1) 跨大关系文件的精确切片（prereq 闭包、related/part_of 过滤）
//   2) 传递闭包（先修链多跳遍历）
// 语义定位、答案/脑图的生成，由 LLM 读取相关 YAML 切片后推理完成。
//
// 用法（任意目录均可，root 由 __dirname 反推，无需 cd）：
//   pnpm exec tsx src/kg_ask.ts tree <textbookId>
//   pnpm exec tsx src/kg_ask.ts concepts <sectionId>
//   pnpm exec tsx src/kg_ask.ts covered  <conceptId>
//   pnpm exec tsx src/kg_ask.ts prereq   <conceptId>   # 传递闭包（算法）
//   pnpm exec tsx src/kg_ask.ts demo     <conceptId>
//   pnpm exec tsx src/kg_ask.ts related  <conceptId>
//   pnpm exec tsx src/kg_ask.ts mindmap  <sectionId>   # 给 LLM 组装脑图用的聚合
import { loadGraph } from './load.js'
import { Query } from './query.js'
import { formatLine, pageSuffix } from './cli_format.js'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 由本文件位置（tools/kg/src）反推 knowledge 仓根，避免依赖 cwd（ESM 下用 import.meta.url）
const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..', '..', '..')
const lg = loadGraph(ROOT)
const q = new Query({ nodes: lg.entities as any, edges: lg.relations as any })

type AnyEntity = Record<string, any>
const title = (e: AnyEntity | undefined): string =>
  e ? (e.name ?? e.title ?? e.id) : '(未知)'
const byId = (id: string) => lg.entities.find((e) => e.id === id)
const relsFrom = (type: string, from: string) =>
  lg.relations.filter((r: any) => r.type === type && r.from === from).map((r: any) => r.to)
const relsTo = (type: string, to: string) =>
  lg.relations.filter((r: any) => r.type === type && r.to === to).map((r: any) => r.from)
// 双向邻接(related 等无向语义关系):出边 to ∪ 入边 from,按 id 去重
const relsBoth = (type: string, id: string) =>
  [...new Set([...relsFrom(type, id), ...relsTo(type, id)])]

function show(entities: AnyEntity[]) {
  if (!entities.length) {
    console.log('(无结果)')
    return
  }
  for (const e of entities) console.log(formatLine(e, title))
}

const argv = process.argv.slice(2)
if (argv[0] === '--') argv.shift()   // 容忍 `pnpm kg:ask -- <cmd>` 的前导分隔符
const [cmd, arg] = [argv[0], argv[1]]

switch (cmd) {
  case 'tree': {
    const { chapters, sections } = q.sectionTree(arg)
    console.log(`# 教材 ${arg}`)
    for (const c of chapters) {
      console.log(`## 章 ${c.id} — ${title(c)}`)
      for (const s of sections.filter((s: AnyEntity) => s.chapterId === c.id))
        console.log(`   - ${s.id} — ${title(s)}${pageSuffix(s)}`)
    }
    break
  }
  case 'concepts':
    show(q.conceptsForSection(arg))
    break
  case 'covered':
    show(q.coveredBySection(arg))
    break
  case 'prereq':
    show(q.prerequisitesOf(arg))
    break
  case 'demo':
    show(q.itemsDemonstrating(arg))
    break
  case 'related':
    show(relsBoth('related', arg).map(byId).filter(Boolean))
    break
  case 'partof':
    show(relsFrom('part_of', arg).map(byId).filter(Boolean))
    break
  case 'mindmap': {
    const cs = q.conceptsForSection(arg)
    const out = cs.map((c: AnyEntity) => ({
      concept: c.id,
      title: title(c),
      partOf: relsFrom('part_of', c.id),
      prereq: q.prerequisitesOf(c.id).map((p: AnyEntity) => p.id),
      related: relsBoth('related', c.id),
      demonstrates: relsTo('demonstrates', c.id),
    }))
    console.log(JSON.stringify(out, null, 2))
    break
  }
  default:
    console.log('Usage: pnpm exec tsx src/kg_ask.ts <tree|concepts|covered|prereq|demo|related|partof|mindmap> <id>')
}
