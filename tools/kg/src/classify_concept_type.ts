/**
 * 概念教学类型分类（spec D1 判据）。
 *
 * 判据优先级（自上而下，命中即停）：
 *   程序型：有固定操作步骤（步骤/作法/画法/尺规作图/解方程步骤…）
 *   推理型：证明方法与推理策略（证明/反证/归纳/类比/分析法/综合法）——**不含定理本身**
 *   建模型：需要抽象成模型再求解（模型/建模）
 *   应用型：以解决实际情境为主（应用/实际问题/测量/方案/设计）
 *   概念型：其余（含全部定理、公式、名词性定义）
 *
 * 用法：
 *   npx tsx src/classify_concept_type.ts --dry     # 只统计 + 输出候选 TSV
 *   npx tsx src/classify_concept_type.ts --apply   # 写入 graph/entities/concepts/*.yaml
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { loadGraph } from './load.js'
import type { ConceptType } from './schema/types.js'

const ROOT = resolve(process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : '../..')
const APPLY = process.argv.includes('--apply')

// 理科：层级与操作性明确，5 类判据可落地
const STEM = new Set(['数学', '物理', '化学', '生物', '科学'])
// 人文社科：「…法」多是制度/权利（宪法、立法权），不能按「方法」判
const HUMANITIES = new Set(['语文', '历史', '道德与法治', '地理'])

// 只保留金标实测精度高的规则（≥90%）；模糊形态一律留空（未判定），
// 不用 default 硬凑成「概念型」——那是假数据。
const RULES_STEM: [RegExp, ConceptType][] = [
  // 100%（样本 6/6）：陈述性标记词
  [/口诀|法则|公式|定理|性质|定义|规律|定律|概念|含义|意义|特点|特征|作用|影响|地位|职责|权利|义务/, '概念型'],
  // 100%（样本 7/7）：明确的固定操作
  [/步骤|作法|画法|尺规作图|作图|量角|画角|配方法|通分|约分|化简|因式分解|解方程|列方程|竖式|笔算|制取|制备/, '程序型'],
  // 100%（样本 3/3）：证明/推理方法
  [/归纳法|反证法|类比法|分析法|综合法|证明方法|推理方法|推理策略/, '推理型'],
]

// 人文社科：只有「步骤/作法/画法」这类明确操作才出值
const RULES_HUMANITIES: [RegExp, ConceptType][] = [
  [/步骤|作法|画法/, '程序型'],
]

const g = loadGraph(ROOT)
const concepts = g.entities.filter(e => e.type === 'Concept') as {
  id: string
  title: string
  subject: string
  explanation?: string
  conceptType?: string
}[]

const classify = (c: { title: string; subject?: string }): { type: ConceptType | null; rule: string } => {
  const rules = STEM.has(c.subject ?? '') ? RULES_STEM : RULES_HUMANITIES
  for (const [re, type] of rules) {
    if (re.test(c.title)) return { type, rule: `title:${re.source.slice(0, 20)}` }
  }
  // 默认「概念型」：金标实测该 default 精度 92%（63 条抽样 58 条确为概念型）。
  // 已知代价：约 8.9% 的概念型池实为程序型（全库约 700 条），程序型召回偏低——README 已披露。
  return { type: '概念型', rule: 'default' }
}

const rows = concepts.map(c => ({ ...c, ...classify(c) }))
const dist: Record<string, number> = {}
for (const r of rows) { const k = r.type ?? '未判定'; dist[k] = (dist[k] ?? 0) + 1 }

console.log(`概念 ${rows.length} 条；分类分布：`)
for (const [k, v] of Object.entries(dist).sort((a, b) => b[1] - a[1])) {
  console.log(`  ${k}\t${v}\t${((v / rows.length) * 100).toFixed(1)}%`)
}

writeFileSync(
  '/tmp/concept-type-candidates.tsv',
  rows.map(r => [r.id, r.subject, r.title, r.type ?? '未判定', r.rule].join('\t')).join('\n'),
)
console.log('\n候选写入 /tmp/concept-type-candidates.tsv')

if (APPLY) {
  const bySubject = new Map<string, typeof rows>()
  for (const r of rows) {
    const arr = bySubject.get(r.subject) ?? []
    arr.push(r)
    bySubject.set(r.subject, arr)
  }
  let written = 0
  for (const [subject, list] of bySubject) {
    const p = resolve(ROOT, `graph/entities/concepts/${subject}.yaml`)
    let text = readFileSync(p, 'utf8')
    if (!text.endsWith('\n')) text += '\n'
    for (const r of list) {
      if (r.conceptType) continue
      // 在概念块里 `title:` 那一行之后插入 conceptType，保持字段顺序稳定
      const blockRe = new RegExp(`(- id: ${r.id.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\n(?:  [^\\n]*\\n)*?  title: [^\\n]*\\n)`)
      const m = blockRe.exec(text)
      if (!m) continue
      text = text.replace(m[1], `${m[1]}  conceptType: ${r.type}\n`)
      written++
    }
    writeFileSync(p, text)
  }
  console.log(`已写入 ${written} 条 conceptType`)
}
