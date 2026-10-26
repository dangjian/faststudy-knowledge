import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { normTitle } from '../src/title_norm.js'

const vectors = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures/contract/section-title-agree.vectors.json'), 'utf8'),
) as { normTitle: Array<{ input: string; expected: string }> }

test('title_norm 与 golden 向量一致（TS 侧）', () => {
  for (const c of vectors.normTitle) {
    assert.equal(normTitle(c.input), c.expected, c.input)
  }
})
