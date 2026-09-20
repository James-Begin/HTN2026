export type Post = {
  id: string; text: string; publishedAt: string; author: string; handle?: string
  avatar?: string; likes?: number | null; reposts?: number | null; replies?: number | null
  url?: string; parentId?: string | null; quotedPostId?: string | null
  scope?: string; captureTime?: string; textIsExcerpt?: boolean; sourceType?: 'input'
  basetenKind?: string; sameClaimScore?: number; sameClaimRegister?: string; rerankerScore?: number; rerankerModel?: string
  basetenPick?: boolean; semanticScore?: number; lexicalScore?: number
  rankingScore?: number; rankingMethod?: string
  spaceScore?: number; spaceY?: number; spaceZ?: number; spaceDirectionQuality?: number; spaceMethod?: string
}

export type Bucket = {
  day: string
  count: number | null
  coverage: 'complete' | 'partial' | 'sample' | 'unavailable'
  pending?: boolean
}

export type SearchPlan = {
  contextLabel?: string
  entities?: string[]
  angles?: string[]
  uncertainties?: string[]
  volumePhrase?: string
  volumeFallback?: string
  discoveryPhrase?: string | null
  discoveryQueries?: string[]
  expansionQueries?: string[]
  expansionReason?: string
  whyDiscovery?: string
  model?: string | null
  error?: string
}

export type RunModel = {
  openai?: string | null
  baseten?: {
    status?: string
    model?: string | null
    classified?: number
    retrieval?: { status?: string; semantic?: string; reranker?: string }
  } | string
}

export type PeriodResult = {
  day: string
  posts: Post[]
  rankingCoverage: string
  partial: boolean
  xSpend: number
  model: RunModel
}

export type Run = {
  id: string
  seed: string
  title: string
  kind: 'live' | 'saved'
  capturedAt?: string
  scope: string
  query?: string | null
  buckets: Bucket[]
  posts: Post[]
  selectedDay: string
  rankingCoverage: string
  searchPlan?: SearchPlan | null
  model?: RunModel
  note: string
  xSpend?: number
  savedPeriods?: Record<string, PeriodResult>
  streamSource?: 'live' | 'cache' | 'recorded'
  activityScaleMax?: number
  seedPost?: Post
}

export type StreamEvent = {
  runId: string
  sequence: number
  type: string
  payload: Record<string, unknown>
}

export type RunMode = 'live' | 'recorded'
export type RunStatus = 'idle' | 'running' | 'reconnecting' | 'completed' | 'stopped' | 'failed'
