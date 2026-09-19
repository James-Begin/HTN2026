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
  sharedTerms?: string[]
}

export type SemanticEdge = {
  source: string
  target: string
  cosine: number
  model: string
  sharedTerms?: string[]
}

export type StoryRole = 'announcement' | 'reporting' | 'explanation' | 'adoption' | 'critique' | 'question' | 'humor' | 'other'
export type StoryAnnotation = { role: StoryRole; focus?: string }
export type PositionedNode = { id: string; x: number; y: number; lane: number }

export const STORY_LANES = [
  { label: 'Announcement', y: 98 },
  { label: 'Reports & explanation', y: 210 },
  { label: 'Response & adoption', y: 322 },
  { label: 'Critique & questions', y: 434 },
  { label: 'Humor & riffs', y: 546 },
  { label: 'Other captured', y: 658 },
]

export function laneForRole(role: StoryRole | undefined): number {
  if (role === 'announcement') return 0
  if (role === 'reporting' || role === 'explanation') return 1
  if (role === 'adoption') return 2
  if (role === 'critique' || role === 'question') return 3
  if (role === 'humor') return 4
  return 5
}

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
    edges.push({ id, source: pair[0], target: pair[1], type: 'semantic', cosine: candidate.cosine,
      model: candidate.model, sharedTerms: candidate.sharedTerms })
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
function hashId(id: string) {
  let hash = 2166136261
  for (const letter of id) hash = Math.imul(hash ^ letter.charCodeAt(0), 16777619)
  return hash >>> 0
}

/** A global chronology, computed without a focus ID: refocusing never changes topology. */
export function layoutStory(posts: GraphPost[], annotations: Record<string, StoryAnnotation>, seedId: string): PositionedNode[] {
  const chronological = [...posts].sort((a, b) => Date.parse(a.publishedAt) - Date.parse(b.publishedAt) || a.id.localeCompare(b.id))
  const nodes = chronological.map((post, index) => {
    const lane = post.id === seedId ? 0 : laneForRole(annotations[post.id]?.role)
    // Horizontal order is chronology. Equal spacing keeps dense capture bursts
    // legible; horizontal distance is deliberately not an elapsed-time scale.
    const x = 90 + 1055 * index / Math.max(1, chronological.length - 1)
    const jitter = (hashId(post.id) % 79) - 39
    return { id: post.id, x, y: STORY_LANES[lane].y + jitter, lane }
  }).sort((a, b) => a.x - b.x || a.id.localeCompare(b.id))

  // Resolve local overlaps within a strand without moving posts into another
  // strand. This runs on the reference corpus, not whenever focus changes.
  for (let pass = 0; pass < 36; pass++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        if (b.x - a.x > 24) break
        if (a.lane !== b.lane) continue
        const dx = b.x - a.x, dy = b.y - a.y
        const distance = Math.hypot(dx, dy)
        if (distance >= 17) continue
        const push = (17 - distance) / 2
        const sign = dy === 0 ? (hashId(a.id) % 2 ? 1 : -1) : Math.sign(dy)
        a.y = between(a.y - push * sign, STORY_LANES[a.lane].y - 47, STORY_LANES[a.lane].y + 47)
        b.y = between(b.y + push * sign, STORY_LANES[b.lane].y - 47, STORY_LANES[b.lane].y + 47)
        moved = true
      }
    }
    if (!moved) break
  }
  return nodes
}
