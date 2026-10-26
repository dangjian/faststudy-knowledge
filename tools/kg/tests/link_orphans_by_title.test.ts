import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bestSectionFor, bookOfPath } from '../src/link_orphans_by_title.js'

const S = (book: string, grade: string, sec: string, text: string) => ({
  f: `/r/content/${grade}/上册/数学/${book}/chapters/C1/sections/${sec}.md`,
  text,
})

test('bookOfPath 从绝对/相对路径取教材段', () => {
  assert.equal(bookOfPath('/r/content/八年级/上册/数学/BSDU-8-1-Math/chapters/C1/sections/S1.md'), 'BSDU-8-1-Math')
  assert.equal(bookOfPath('content/九年级/全一册/英语/PEP-9-0-English/chapters/C3/sections/S1.md'), 'PEP-9-0-English')
  assert.equal(bookOfPath('graph/x.yaml'), null)
})

test('bestSectionFor 只在给定池内取标题出现最多且节存在的文件', () => {
  const a1 = S('BSDU-8-1-Math', '八年级', 'S1', '勾股定理')
  const a2 = S('BSDU-8-1-Math', '八年级', 'S2', '勾股定理……勾股定理')
  const other = S('BSDU-5-1-Math', '五年级', 'S1', '勾股定理 勾股定理 勾股定理')
  const ids = new Set(['BSDU-8-1-Math-C1-S1', 'BSDU-8-1-Math-C1-S2', 'BSDU-5-1-Math-C1-S1'])
  const pool = [a1, a2, other].filter(s => bookOfPath(s.f) === 'BSDU-8-1-Math')
  assert.equal(bestSectionFor('勾股定理', pool, ids), a2.f)
  assert.equal(bestSectionFor('勾股定理', pool, new Set(['BSDU-8-1-Math-C1-S1'])), a1.f) // S2 节实体不存在
  assert.equal(bestSectionFor('相似三角形', pool, ids), null)
})

test('bestSectionFor 不计表格行中的出现（门 B 第 1 轮：插图残渣/生字表误命中）', () => {
  const t = S('BSDU-8-1-Math', '八年级', 'S1', '| 攻占巴士底狱 | 插图 |\n\n正文没有这个词')
  const u = S('BSDU-8-1-Math', '八年级', 'S2', '攻占巴士底狱发生在 1789 年')
  const ids = new Set(['BSDU-8-1-Math-C1-S1', 'BSDU-8-1-Math-C1-S2'])
  assert.equal(bestSectionFor('攻占巴士底狱', [t, u], ids), u.f) // S1 只在表格行
  assert.equal(bestSectionFor('攻占巴士底狱', [t], ids), null) // 只有表格行 → 不匹配
})
