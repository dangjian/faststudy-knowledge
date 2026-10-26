import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sectionIdFromSourceRef } from '../src/fix_covered_by.js'

test('sectionIdFromSourceRef 认一至九年级与全一册', () => {
  assert.equal(
    sectionIdFromSourceRef('content/一年级/上册/数学/PEP-1-1-Math/chapters/C1/sections/S2.md'),
    'PEP-1-1-Math-C1-S2',
  )
  assert.equal(
    sectionIdFromSourceRef('content/九年级/全一册/英语/PEP-9-0-English/chapters/C3/sections/S1.md'),
    'PEP-9-0-English-C3-S1',
  )
  assert.equal(
    sectionIdFromSourceRef('content/七年级/下册/地理/ZTB-7-2-Geography/chapters/C9/sections/S1.md'),
    'ZTB-7-2-Geography-C9-S1',
  )
})

test('sectionIdFromSourceRef 章级 index 与缺 content/ 前缀不匹配', () => {
  assert.equal(sectionIdFromSourceRef('content/三年级/上册/科学/ES-3-1-Science/chapters/C1/index.md'), null)
  assert.equal(sectionIdFromSourceRef('三年级/上册/科学/ES-3-1-Science/chapters/C1/sections/S1.md'), null)
})

test('rewriteSourceRefs 只改目标概念的顶层 sourceRef 行，其余逐字节不变', async () => {
  const { rewriteSourceRefs } = await import('../src/link_orphans_by_title.js')
  const text = [
    '- id: concept:数学:分数',
    '  misconceptions:',
    '  - sourceRef: 不是字段',
    '  sourceRef: content/七年级/上册/数学/X/chapters/C1/sections/S1.md',
    '- id: concept:数学:小数',
    '  sourceRef: content/七年级/上册/数学/X/chapters/C1/sections/S2.md',
    '',
  ].join('\n')
  const out = rewriteSourceRefs(
    text,
    new Map([['concept:数学:分数', 'content/三年级/上册/数学/PEP-3-1-Math/chapters/C8/sections/S1.md']]),
  )
  assert.equal(
    out,
    text.replace(
      '  sourceRef: content/七年级/上册/数学/X/chapters/C1/sections/S1.md',
      '  sourceRef: content/三年级/上册/数学/PEP-3-1-Math/chapters/C8/sections/S1.md',
    ),
  )
})
