import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'
import type { Ontology } from './schema/types.js'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')

export function loadOntology(ontologyPath = resolve(ROOT, 'graph/ontology.yaml')): Ontology {
  const raw = readFileSync(ontologyPath, 'utf8')
  return parse(raw) as Ontology
}
