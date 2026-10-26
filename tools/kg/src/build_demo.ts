/**
 * 生成静态树浏览器的数据包（demo/data/*.json）。
 *
 * 为什么单独建一份而不是直接给 dist/graph.json：
 *   dist 是全量图（11.7MB），浏览器首屏只需「教材→章→节」的树（277KB）。
 *   概念详情按学科懒加载（4.1MB 总量，单科最大 800KB），不占首屏。
 *
 * 用法：`pnpm kg:demo`（在 knowledge 根目录），产物进 demo/data/。
 */
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, cpSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import { loadGraph } from './load.js'

// 与其他脚本一致的参数约定：跳过 `--` 等短横线开头的参数，取第一个普通参数作为仓库根
const ROOT = resolve(process.argv.slice(2).find((a) => !a.startsWith('-')) ?? '../..')
const OUT = resolve(ROOT, 'demo/data')

type Tree = { i: string; t: string; k: 'b' | 'c' | 's'; p: string | null }

const main = (): void => {
  const g = loadGraph(ROOT)
  const byId = new Map(g.entities.map(e => [e.id, e as Record<string, unknown>]))

  // standards / gradeRange 是 build 派生字段，YAML 源里没有 → 必须从 dist 合并。
  // （同类坑已踩过四次：standards、conceptType、masteryCriteria、strength 都曾被投影或派生漏掉。）
  type Derived = { standards?: string[]; gradeRange?: string }
  const derived = new Map<string, Derived>()
  try {
    const dist = JSON.parse(readFileSync(resolve(ROOT, 'dist/graph.json'), 'utf8')) as {
      nodes: ({ id: string } & Derived)[]
    }
    for (const n of dist.nodes) derived.set(n.id, { standards: n.standards, gradeRange: n.gradeRange })
  } catch {
    throw new Error('缺少 dist/graph.json —— 先跑 `pnpm kg:build` 再跑 `pnpm kg:demo`')
  }

  // ---------- 1. 树：教材 → 章 → 节 ----------
  const tree: Tree[] = []
  for (const e of g.entities) {
    const n = e as Record<string, unknown>
    if (n.type === 'Textbook') {
      tree.push({ i: n.id as string, t: (n.title as string) ?? '', k: 'b', p: null })
    } else if (n.type === 'Chapter') {
      tree.push({ i: n.id as string, t: (n.title as string) ?? '', k: 'c', p: (n.textbookId as string) ?? null })
    } else if (n.type === 'Section') {
      tree.push({ i: n.id as string, t: (n.title as string) ?? '', k: 's', p: (n.chapterId as string) ?? null })
    }
  }

  // ---------- 2. 节点详情：册/章 = 元信息；节 = 页码 + 概念清单；概念 = 全字段 ----------
  const conceptOfSection = new Map<string, string[]>()
  for (const r of g.relations) {
    if (r.type !== 'covered_by') continue
    const arr = conceptOfSection.get(String(r.to)) ?? []
    arr.push(String(r.from))
    conceptOfSection.set(String(r.to), arr)
  }

  const nodeDetail: Record<string, unknown> = {}
  for (const e of g.entities) {
    const n = e as Record<string, unknown>
    if (n.type === 'Textbook') {
      nodeDetail[n.id as string] = {
        kind: 'textbook', title: n.title, subject: n.subject,
        grade: n.grade, term: n.term, publisher: n.publisher, totalPages: n.totalPages,
      }
    } else if (n.type === 'Chapter') {
      nodeDetail[n.id as string] = { kind: 'chapter', title: n.title, pageRange: n.pageRange }
    } else if (n.type === 'Section') {
      nodeDetail[n.id as string] = {
        kind: 'section',
        title: n.title,
        pageRange: n.pageRange,
        sourceRef: n.sourceRef,
        concepts: (conceptOfSection.get(n.id as string) ?? []).map(id => ({
          id, title: (byId.get(id) as { title?: string } | undefined)?.title ?? '',
        })),
      }
    }
  }

  // ---------- 3. 概念详情（按学科分片）----------
  const pre = new Map<string, { to: string; s?: string }[]>()
  const broader = new Map<string, string[]>()
  const related = new Map<string, string[]>()
  const covered = new Map<string, string[]>()
  for (const r of g.relations) {
    const f = String(r.from), t = String(r.to)
    if (r.type === 'prerequisite') {
      const arr = pre.get(f) ?? []
      arr.push({ to: t, s: (r as { strength?: string }).strength })
      pre.set(f, arr)
    } else if (r.type === 'part_of') {
      const arr = broader.get(f) ?? []
      arr.push(t)
      broader.set(f, arr)
    } else if (r.type === 'related') {
      const arr = related.get(f) ?? []
      arr.push(t)
      related.set(f, arr)
    } else if (r.type === 'covered_by') {
      const arr = covered.get(f) ?? []
      arr.push(t)
      covered.set(f, arr)
    }
  }

  // 课标码 → 主题名（UI 显示中文，不显示 std-biology-2022-PH）
  const stdPath = resolve(ROOT, 'graph/curriculum-standards.yaml')
  const stdTheme = new Map<string, string>()
  for (const s of parse(readFileSync(stdPath, 'utf8')) as { id: string; theme?: string }[]) {
    if (s.id) stdTheme.set(s.id, s.theme ?? s.id)
  }

  const bySubject = new Map<string, Record<string, unknown>[]>()
  for (const e of g.entities) {
    const n = e as Record<string, unknown>
    if (n.type !== 'Concept') continue
    const id = n.id as string
    const nameOf = (x: string): string => (byId.get(x) as { title?: string } | undefined)?.title ?? x
    const item = {
      id,
      title: n.title,
      subject: n.subject,
      conceptType: n.conceptType ?? null,
      explanation: n.explanation ?? '',
      misconceptions: n.misconceptions ?? [],
      masteryCriteria: n.masteryCriteria ?? [],
      gradeRange: derived.get(id)?.gradeRange ?? null,
      standards: ((derived.get(id)?.standards ?? (n.standards as string[] | undefined)) ?? []).map(s => ({ id: s, theme: stdTheme.get(s) ?? s })),
      prereq: (pre.get(id) ?? []).map(p => ({ id: p.to, title: nameOf(p.to), strength: p.s ?? null })),
      broader: (broader.get(id) ?? []).map(b => ({ id: b, title: nameOf(b) })),
      related: (related.get(id) ?? []).slice(0, 8).map(b => ({ id: b, title: nameOf(b) })),
      sections: (covered.get(id) ?? []).map(sid => {
        const s = byId.get(sid) as { title?: string; pageRange?: number[] } | undefined
        return { id: sid, title: s?.title ?? '', pageRange: s?.pageRange ?? null }
      }),
    }
    const arr = bySubject.get(String(n.subject)) ?? []
    arr.push(item)
    bySubject.set(String(n.subject), arr)
  }

  // ---------- 写盘 ----------
  mkdirSync(resolve(OUT, 'concepts'), { recursive: true })
  const w = (p: string, data: unknown): number => {
    const s = JSON.stringify(data)
    writeFileSync(resolve(OUT, p), s)
    return s.length
  }
  let total = 0
  total += w('tree.json', tree)
  total += w('detail.json', nodeDetail)
  for (const [subject, items] of bySubject) {
    total += w(`concepts/${subject}.json`, items)
  }
  // 目录：学科 → 教材清单（首屏按学科折叠）
  const catalog: Record<string, { id: string; title: string; grade: string; term: string }[]> = {}
  for (const e of g.entities) {
    const n = e as Record<string, unknown>
    if (n.type !== 'Textbook') continue
    const arr = catalog[String(n.subject)] ?? []
    arr.push({ id: n.id as string, title: (n.title as string) ?? '', grade: String(n.grade ?? ''), term: String(n.term ?? '') })
    catalog[String(n.subject)] = arr
  }
  total += w('catalog.json', catalog)
  // contentBase：从仓库根起服务时原文可直接打开；repoWeb 为空表示用本地路径
  total += w('config.json', { contentBase: '/', repoWeb: '' })
  // 邻接表：关系网视图用（1.37MB，点击「关系网」时懒加载）
  const adj: Record<string, [string, string, string][]> = {}
  for (const r of g.relations) {
    const t = String(r.type)
    if (!['prerequisite', 'part_of', 'related'].includes(t)) continue
    const key = t === 'prerequisite' ? 'p' : t === 'part_of' ? 'o' : 'r'
    const st = String((r as { strength?: string }).strength ?? '')
    ;(adj[String(r.from)] ??= []).push([String(r.to), key, t === 'prerequisite' ? st : ''])
    ;(adj[String(r.to)] ??= []).push([String(r.from), key, t === 'prerequisite' ? st : ''])
  }
  total += w('adj.json', adj)

  // 学科 × 年级 热力矩阵：首屏概览。gradeRange 在不同教材可能跨年级，
  // 这里按「概念出现的最低年级」归格，避免一条概念重复计数。
  const matrix: { subject: string; grade: number; concepts: number }[] = []
  const cell = new Map<string, number>()
  for (const e of g.entities) {
    const n = e as Record<string, unknown>
    if (n.type !== 'Concept') continue
    const gr = String(derived.get(n.id as string)?.gradeRange ?? '')
    const m = /(\d)/.exec(gr)
    if (!m) continue
    const key = `${String(n.subject)}|${m[1]}`
    cell.set(key, (cell.get(key) ?? 0) + 1)
  }
  for (const [k, v] of cell) {
    const [subject, grade] = k.split('|')
    matrix.push({ subject, grade: Number(grade), concepts: v })
  }
  total += w('matrix.json', matrix)
  // 概念检索索引：树里只有教材/章/节标题，搜「光合作用」必须能命中概念本身
  const searchIndex = [...bySubject.values()].flat().map(c => ({ i: c.id as string, t: c.title as string, s: c.subject as string }))
  total += w('search.json', searchIndex)

  // 公式渲染库：只对含 $ 的节懒加载，但文件需随 demo 一起分发（3.8% 的节有公式）
  const katexSrc = [
    resolve(ROOT, 'tools/kg/node_modules/katex/dist'),
    resolve(ROOT, 'node_modules/katex/dist'),
  ].find((d) => existsSync(d)) ?? resolve(ROOT, 'node_modules/katex/dist')
  const katexDst = resolve(ROOT, 'demo/vendor/katex')
  try {
    mkdirSync(resolve(katexDst, 'contrib'), { recursive: true })
    copyFileSync(resolve(katexSrc, 'katex.min.js'), resolve(katexDst, 'katex.min.js'))
    copyFileSync(resolve(katexSrc, 'katex.min.css'), resolve(katexDst, 'katex.min.css'))
    copyFileSync(resolve(katexSrc, 'contrib/auto-render.min.js'), resolve(katexDst, 'contrib/auto-render.min.js'))
    cpSync(resolve(katexSrc, 'fonts'), resolve(katexDst, 'fonts'), { recursive: true })
    console.log('katex 已拷入 demo/vendor/katex')
  } catch {
    console.log('⚠ 未找到 katex（npm i -D katex 后重跑），公式将降级为等宽文本')
  }

  const kb = (n: number): string => `${(n / 1024).toFixed(0)}KB`
  console.log(`树 ${tree.length} 节点 → ${kb(JSON.stringify(tree).length)}`)
  console.log(`节点详情 ${Object.keys(nodeDetail).length} 条 → ${kb(JSON.stringify(nodeDetail).length)}`)
  console.log(`概念 ${[...bySubject.values()].reduce((a, x) => a + x.length, 0)} 条 → ${bySubject.size} 个学科分片，合计 ${kb([...bySubject.values()].reduce((a, x) => a + JSON.stringify(x).length, 0))}`)
  console.log(`全部写出 ${kb(total)} → ${OUT}`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
