// resolveProse 跨仓契约（knowledge 侧）。
// 应用侧同名契约测试拿同一份 fixture 跑同一批 cases，
// 两侧的手抄实现一旦漂移，必有一侧变红。契约的由来见 docs/KG_MAINTENANCE_BACKLOG.md 第 1 项。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { resolveProse } from '../src/prose.js'

const contractPath = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures/contract/prose.json')
const contract = JSON.parse(readFileSync(contractPath, 'utf-8'))

function setupRoot(): string {
  const root = mkdtempSync(join(tmpdir(), 'kg-prose-'))
  for (const [rel, text] of Object.entries(contract.files as Record<string, string>)) {
    const abs = join(root, rel)
    mkdirSync(dirname(abs), { recursive: true })
    writeFileSync(abs, text)
  }
  return root
}

const root = setupRoot()

for (const c of contract.cases as Array<Record<string, any>>) {
  test(`resolveProse 契约：${c.name}`, () => {
    if (c.expectedErrorPattern) {
      assert.throws(() => resolveProse(root, c.sourceRef), new RegExp(c.expectedErrorPattern))
      return
    }
    assert.deepStrictEqual(resolveProse(root, c.sourceRef), c.expected)
  })
}
