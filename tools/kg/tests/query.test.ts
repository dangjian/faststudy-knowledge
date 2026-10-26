import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Query } from '../src/query.js'
import { build } from '../src/build.js'
import { loadGraph } from '../src/load.js'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures')
const q = new Query(build(loadGraph(fixtures)).graph)

test('conceptsForSection', () => {
  const cs = q.conceptsForSection('PEP-7-2-English-C1-S1')
  assert.ok(cs.some(c => c.id === 'concept:english:be-verb'))
})

test('itemsDemonstrating', () => {
  const items = q.itemsDemonstrating('concept:english:animal-vocab')
  assert.ok(items.some(i => i.id === 'word:PEP-7-2-English-U1:fox'))
})

test('prerequisitesOf 递归', () => {
  const pres = q.prerequisitesOf('concept:english:present-continuous')
  assert.ok(pres.some(c => c.id === 'concept:english:be-verb'))
})

test('sectionTree', () => {
  const t = q.sectionTree('PEP-7-2-English')
  assert.ok(t.sections.some(s => s.id === 'PEP-7-2-English-C1-S1'))
})
