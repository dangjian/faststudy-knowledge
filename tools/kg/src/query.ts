import type { Graph, Entity, RelationEdge } from './schema/types.js'

export class Query {
  private byId: Map<string, Entity>
  private edges: RelationEdge[]
  constructor(graph: Graph) {
    this.byId = new Map(graph.nodes.map(n => [n.id, n]))
    this.edges = graph.edges
  }

  conceptsForSection(sectionId: string): Entity[] {
    return this.edges
      .filter(r => r.type === 'covered_by' && r.to === sectionId)
      .map(r => this.byId.get(r.from))
      .filter((e): e is Entity => !!e)
  }

  prerequisitesOf(conceptId: string): Entity[] {
    const visited = new Set<string>()
    const stack = [conceptId]
    while (stack.length) {
      const cur = stack.pop()!
      for (const r of this.edges) {
        if (r.type === 'prerequisite' && r.from === cur && !visited.has(r.to)) {
          visited.add(r.to)
          stack.push(r.to)
        }
      }
    }
    return [...visited].map(id => this.byId.get(id)).filter((e): e is Entity => !!e)
  }

  itemsDemonstrating(conceptId: string): Entity[] {
    return this.edges
      .filter(r => r.type === 'demonstrates' && r.to === conceptId)
      .map(r => this.byId.get(r.from))
      .filter((e): e is Entity => !!e)
  }

  coveredBySection(conceptId: string): Entity[] {
    return this.edges
      .filter(r => r.type === 'covered_by' && r.from === conceptId)
      .map(r => this.byId.get(r.to))
      .filter((e): e is Entity => !!e)
  }

  sectionTree(textbookId: string): { chapters: Entity[]; sections: Entity[] } {
    const chapters = [...this.byId.values()].filter(e => e.type === 'Chapter' && (e as Record<string, unknown>).textbookId === textbookId)
    const sections = [...this.byId.values()].filter(e => e.type === 'Section' && (e as Record<string, unknown>).textbookId === textbookId)
    return { chapters, sections }
  }
}
