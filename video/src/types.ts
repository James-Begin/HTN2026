export type Node = {
  id: string
  author: string
  handle: string
  text: string
  publishedAt: string
  likes: number
  parentId?: string | null
  quotedPostId?: string | null
  branch: string
  cosine: number
  x: number
  y: number
  depth: number
  order: number
}

export type Edge = { from: string; to: string; kind: 'reply' | 'quote' }
export type Bucket = { day: string; count: number }
export type DemoData = {
  seedId: string
  seedText: string
  title: string
  nodes: Node[]
  edges: Edge[]
  buckets: Bucket[]
}
