import { readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import { parseSupplement } from './items_md.js'

// 按 sourceRef 取 content/ 下的正文。
//
// 为什么不水化进 graph.json：Section 正文合计 22 MB，而 graph.json 已经 17.5 MB。
// 把正文灌进产物会让常驻内存翻倍，可正文是低频、按需读的（预习/课文一次只看一节）。
// 所以 dist 保持不变，取正文走这条按需读文件的路。
//
// front-matter 只剥不解释——其内容合法性由 lint（rule 16 等）保证，不是本原语的职责。
//
// ⚠️ 与下游应用侧同名服务（kg-content.service）是同一份逻辑的两处手抄实现
// （CLAUDE.md 3.2 的已知例外，与 reviewUnit 同），由 tests/fixtures/contract/prose.json
// 的跨仓契约锁住，改一侧必须同步改另一侧。
// 已知的唯一差异：这里复用 parseSupplement 会顺带 yaml.parse，front-matter 语法坏了这边抛、
// 应用侧不抛（那边不引 yaml 依赖）。lint 不会放这种文件进库，契约也不覆盖该场景。

/** `## 标题 {#anchor}` —— 与 items_md.ts 的 `### E1 {#exercise:…}` 同构，但不限层级与前缀 */
const ANCHORED_HEADING = /^(#{1,6})\s+(.*?)\s*\{#(.+?)\}\s*$/
const PLAIN_HEADING = /^(#{1,6})\s+(.+?)\s*$/

export interface Prose {
  /** 有锚点时为该标题文本；无锚点时为文件里第一个标题，都没有则空串 */
  title: string
  body: string
}

/**
 * @param root      knowledge 仓库根（sourceRef 自带 `content/` 前缀）
 * @param sourceRef `content/…/S1.md` 或 `content/…/S1.md#锚点`
 */
export function resolveProse(root: string, sourceRef: string): Prose {
  const hash = sourceRef.indexOf('#')
  const relPath = hash === -1 ? sourceRef : sourceRef.slice(0, hash)
  const anchor = hash === -1 ? null : sourceRef.slice(hash + 1)

  const rootAbs = resolve(root)
  const fileAbs = resolve(rootAbs, relPath)
  // sourceRef 来自图谱（可信），但越界读文件的代价太大，仍然显式挡一道
  if (fileAbs !== rootAbs && !fileAbs.startsWith(rootAbs + sep)) {
    throw new Error(`sourceRef 越界，不在知识库根内: ${sourceRef}`)
  }

  const { body } = parseSupplement(readFileSync(fileAbs, 'utf8'))
  const lines = body.split('\n')

  if (anchor === null) {
    let title = ''
    for (const line of lines) {
      const m = line.match(PLAIN_HEADING)
      if (m) {
        title = m[2]!.replace(/\s*\{#.+?\}\s*$/, '')
        break
      }
    }
    return { title, body }
  }

  let level = 0
  let title = ''
  const collected: string[] = []
  for (const line of lines) {
    if (level === 0) {
      const m = line.match(ANCHORED_HEADING)
      if (m && m[3] === anchor) {
        level = m[1]!.length
        title = m[2]!
      }
      continue
    }
    // 同级或更高级的标题即为本段终点（无论有无锚点）
    const h = line.match(PLAIN_HEADING)
    if (h && h[1]!.length <= level) break
    collected.push(line)
  }
  // Fail Loud（CLAUDE.md 4.3）：锚点找不到就是图谱与 content 不同步，返回空串会把这种不同步藏起来
  if (level === 0) throw new Error(`锚点不存在: #${anchor}（${relPath}）`)

  while (collected.length > 0 && collected[0] === '') collected.shift()
  while (collected.length > 0 && collected[collected.length - 1] === '') collected.pop()
  return { title, body: collected.join('\n') }
}
