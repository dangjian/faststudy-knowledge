import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadSuspendedEdges } from '../src/lint.js'

function tmpRoot(): string {
  return mkdtempSync(join(tmpdir(), 'kg-suspend-'))
}

test('loadSuspendedEdges: graph/suspended-prerequisites.json 正常加载', () => {
  const root = tmpRoot()
  mkdirSync(join(root, 'graph'))
  writeFileSync(join(root, 'graph', 'suspended-prerequisites.json'), JSON.stringify(['a|b', 'c|d']))
  const s = loadSuspendedEdges(root)
  assert.equal(s.size, 2)
  assert.ok(s.has('a|b') && s.has('c|d'))
})

test('loadSuspendedEdges: 文件不存在 → 空集合', () => {
  assert.equal(loadSuspendedEdges(tmpRoot()).size, 0)
})

test('loadSuspendedEdges: JSON 损坏 → fail loud 抛错', () => {
  const root = tmpRoot()
  mkdirSync(join(root, 'graph'))
  writeFileSync(join(root, 'graph', 'suspended-prerequisites.json'), '{oops')
  assert.throws(() => loadSuspendedEdges(root), /解析失败/)
})

test('loadSuspendedEdges: 非数组 → 抛错', () => {
  const root = tmpRoot()
  mkdirSync(join(root, 'graph'))
  writeFileSync(join(root, 'graph', 'suspended-prerequisites.json'), '{"a":1}')
  assert.throws(() => loadSuspendedEdges(root), /格式错误/)
})
