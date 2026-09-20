export type GraphPost = {
  id: string
  text: string
  publishedAt: string
  author: string
  handle?: string
  avatar?: string
  likes?: number | null
  reposts?: number | null
  replies?: number | null
  followers?: number | null
  url?: string
  parentId?: string | null
  quotedPostId?: string | null
  scope?: string
  textIsExcerpt?: boolean
  spaceScore?: number
  spaceY?: number
  spaceZ?: number
  spaceDirectionQuality?: number
  spaceMethod?: string
  semanticScore?: number
  lexicalScore?: number
  rankingScore?: number
}
