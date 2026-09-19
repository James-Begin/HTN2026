export type GraphPost = {
  id: string
  text: string
  publishedAt: string
  author: string
  handle?: string
  avatar?: string
  likes?: number | null
  url?: string
  parentId?: string | null
  quotedPostId?: string | null
  scope?: string
  textIsExcerpt?: boolean
}

export type GraphEdge = {
  id: string
  source: string
  target: string
  type: 'reply' | 'quote' | 'semantic'
  cosine?: number
  model?: string
}

export type SemanticEdge = {
  source: string
  target: string
  cosine: number
  model: string
}

export type PositionedNode = { id: string; x: number; y: number; depth: number }

export function buildObservedEdges(posts: GraphPost[]): GraphEdge[] {
  const ids = new Set(posts.map(post => post.id))
  const edges: GraphEdge[] = []
  for (const post of posts) {
    const refs: [GraphEdge['type'], string | null | undefined][] = [
      ['reply', post.parentId], ['quote', post.quotedPostId],
    ]
    for (const [type, target] of refs) {
      if (target && target !== post.id && ids.has(target)) {
        edges.push({ id: `${type}:${post.id}:${target}`, source: post.id, target, type })
      }
    }
  }
  return edges
}

export function buildSemanticEdges(posts: GraphPost[], candidates: SemanticEdge[]): GraphEdge[] {
  const ids = new Set(posts.map(post => post.id))
  const seen = new Set<string>()
  const edges: GraphEdge[] = []
  for (const candidate of candidates) {
    if (!ids.has(candidate.source) || !ids.has(candidate.target) || candidate.source === candidate.target
      || !Number.isFinite(candidate.cosine) || !candidate.model) continue
    const pair = [candidate.source, candidate.target].sort()
    const id = `semantic:${pair[0]}:${pair[1]}`
    if (seen.has(id)) continue
    seen.add(id)
    edges.push({ id, source: pair[0], target: pair[1], type: 'semantic', cosine: candidate.cosine, model: candidate.model })
  }
  return edges
}

export function connectedComponent(focusId: string, edges: GraphEdge[]): string[] {
  const adjacency = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set())
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set())
    adjacency.get(edge.source)!.add(edge.target)
    adjacency.get(edge.target)!.add(edge.source)
  }
  const visited = new Set([focusId])
  const queue = [focusId]
  for (let index = 0; index < queue.length; index++) {
    for (const neighbor of adjacency.get(queue[index]) || []) {
      if (!visited.has(neighbor)) { visited.add(neighbor); queue.push(neighbor) }
    }
  }
  return queue
}

function between(value: number, low: number, high: number) { return Math.min(high, Math.max(low, value)) }

/** Stable, evidence-driven structure: edge type determines the arc; distance does not encode strength. */
export function layoutNeighborhood(focusId: string, edges: GraphEdge[], posts: GraphPost[]): PositionedNode[] {
  const byId = new Map(posts.map(post => [post.id, post]))
  const adjacency = new Map<string, GraphEdge[]>()
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, [])
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, [])
    adjacency.get(edge.source)!.push(edge)
    adjacency.get(edge.target)!.push(edge)
  }
  const visited = new Set([focusId])
  const direct = [...(adjacency.get(focusId) || [])].map(edge => ({
    edge,
    id: edge.source === focusId ? edge.target : edge.source,
  })).filter(({ id }) => {
    if (visited.has(id)) return false
    visited.add(id)
    return true
  }).sort((a, b) => {
    const sideA = a.edge.type === 'quote' ? 0 : a.edge.type === 'semantic' ? 1 : 2
    const sideB = b.edge.type === 'quote' ? 0 : b.edge.type === 'semantic' ? 1 : 2
    return sideA - sideB || (byId.get(a.id)?.publishedAt || '').localeCompare(byId.get(b.id)?.publishedAt || '') || a.id.localeCompare(b.id)
  })
  const result: PositionedNode[] = [{ id: focusId, x: 500, y: 320, depth: 0 }]
  const groups = [
    { nodes: direct.filter(item => item.edge.type === 'quote'), start: 98, end: 262 },
    { nodes: direct.filter(item => item.edge.type === 'reply'), start: -82, end: 82 },
    { nodes: direct.filter(item => item.edge.type === 'semantic'), start: 0, end: 360 },
  ]
  for (const group of groups) {
    const caps = [14, 20, 26, 34]
    let cursor = 0
    let ring = 0
    while (cursor < group.nodes.length) {
      const count = Math.min(caps[ring] || 40, group.nodes.length - cursor)
      const radius = Math.min(286, 132 + ring * 71)
      for (let i = 0; i < count; i++) {
        const fraction = count === 1 ? .5 : (i + .5) / count
        const angle = (group.start + (group.end - group.start) * fraction) * Math.PI / 180
        const id = group.nodes[cursor + i].id
        result.push({ id, x: between(500 + Math.cos(angle) * radius, 24, 976), y: between(320 + Math.sin(angle) * radius, 24, 616), depth: 1 })
      }
      cursor += count
      ring++
    }
  }
  const locations = new Map(result.map(node => [node.id, node]))
  const queue = [...result.filter(node => node.depth === 1)]
  for (let index = 0; index < queue.length; index++) {
    const parent = queue[index]
    if (parent.depth > 3) continue
    const newNeighbors = (adjacency.get(parent.id) || []).map(edge => edge.source === parent.id ? edge.target : edge.source)
      .filter(id => !visited.has(id)).sort()
    for (let childIndex = 0; childIndex < newNeighbors.length; childIndex++) {
      const id = newNeighbors[childIndex]
      visited.add(id)
      const base = Math.atan2(parent.y - 320, parent.x - 500)
      const offset = (childIndex - (newNeighbors.length - 1) / 2) * .23
      const angle = base + offset
      const node = {
        id,
        x: between(parent.x + Math.cos(angle) * 50, 20, 980),
        y: between(parent.y + Math.sin(angle) * 50, 20, 620),
        depth: parent.depth + 1,
      }
      locations.set(id, node)
      result.push(node)
      queue.push(node)
    }
  }
  return result
}
