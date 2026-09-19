// Normalized frontend contract. A future transport adapter must translate the
// Python wire events into these events; this is not a claim of wire compatibility.
export type Mode = 'lineage' | 'verify' | 'resolve'
export type Verdict = 'same' | 'uncertain' | 'different' | 'meta'
export type Provenance = 'preview' | 'recorded' | 'live'
export type TimelineSelection = { year: number; month?: number }
export type TimelineBucket = {
  year: number
  month: number
  count: number | null
  coverage: 'complete' | 'partial' | 'unavailable'
}
export type TimelineData = {
  buckets: TimelineBucket[]
  provenance: 'illustrative' | 'measured' | 'sample'
  query: string
  window?: { start: string; end: string }
  preferredPeriod?: TimelineSelection
}
export type Judgment = {
  verdict: Verdict
  explanation?: string
  labelSource: 'fixture' | 'model' | 'editorial'
}
export type Evidence = {
  // Stable identity within the run; fixture IDs are NOT X post IDs.
  id: string
  author: string
  text: string
  context?: string
  url?: string
  postId?: string
  publishedAt?: string
  likes?: number
  verdict?: Verdict
  explanation?: string
  labelSource?: Judgment['labelSource']
  authorId?: string
  handle?: string
  quotedPostId?: string
  capture?: {
    method: string
    endpoint: string
    capturedAt: string
    textIsExcerpt: boolean
    sha256: string
    rawFile: string
    discoveredVia: string
  }
}
export type TraceMoment = {
  id: string
  title: string
  description: string
  date?: string
  evidenceId?: string
  url?: string
  label?: string
}
export type RecordingMetadata = {
  capturedAt: string
  sourceCount: number
  primaryUrl: string
  essayUrl: string
  description: string
  limitations: string[]
  files: string[]
}
export type InvestigationInfo = {
  runId: string; claim: string; mode: Mode; provenance: Provenance
  recording?: RecordingMetadata
}
export type InvestigationStatus = 'idle' | 'running' | 'complete' | 'stopped' | 'failed'
export type InvestigationState = InvestigationInfo & {
  status: InvestigationStatus
  lastSequence: number
  stage: string | null
  timeline: TimelineData | null
  posts: Evidence[]
  observations: TraceMoment[]
  judgments: Record<string, Judgment>
  explanation: { title: string; text: string; started: boolean }
  error: string | null
}

type EventPayload =
  | { kind: 'started' }
  | { kind: 'stage'; name: string }
  | { kind: 'activity'; timeline: TimelineData }
  | { kind: 'post'; post: Evidence }
  // postId references Evidence.id (the run-local key), not Evidence.postId (X ID).
  | { kind: 'score'; postId: string; judgment: Judgment }
  | { kind: 'observation'; observation: TraceMoment }
  | { kind: 'explanation'; title: string }
  | { kind: 'token'; text: string }
  | { kind: 'done' }
  | { kind: 'stopped' }
  | { kind: 'error'; message: string; fatal: boolean }
export type InvestigationEvent = EventPayload & { runId: string; sequence: number }
export type InvestigationEventPayload = EventPayload
export type ScheduledEvent = { at: number; event: InvestigationEvent }
export type PlaybackSource = { info: InvestigationInfo; events: ScheduledEvent[] }

export function createInvestigationState(info: InvestigationInfo): InvestigationState {
  return {
    ...info, status: 'idle', lastSequence: 0, stage: null, timeline: null,
    posts: [], observations: [], judgments: {},
    explanation: { title: '', text: '', started: false }, error: null,
  }
}

export function isTerminal(status: InvestigationStatus) {
  return status === 'complete' || status === 'stopped' || status === 'failed'
}

// Undefined metadata means "not supplied", not "erase an existing value".
function supplied<T extends object>(value: T): Partial<T> {
  return Object.fromEntries(Object.entries(value).filter(([, field]) => field !== undefined)) as Partial<T>
}
function upsert<T extends { id: string }>(items: T[], item: T): T[] {
  const index = items.findIndex(existing => existing.id === item.id)
  return index < 0 ? [...items, item] : items.map((existing, i) => i === index ? { ...existing, ...supplied(item) } : existing)
}

// Ordered events per run. Duplicate/older events, other runs, and late events
// after a terminal outcome cannot mutate the visible investigation. Reset/replay
// creates fresh state rather than sending a second "started" into a finished run.
export function investigationReducer(state: InvestigationState, event: InvestigationEvent): InvestigationState {
  if (event.runId !== state.runId || event.sequence <= state.lastSequence || isTerminal(state.status)) return state
  const next = { ...state, lastSequence: event.sequence }
  switch (event.kind) {
    case 'started': return { ...next, status: 'running' }
    case 'stage': return { ...next, stage: event.name }
    case 'activity': return { ...next, timeline: event.timeline }
    case 'post': {
      const judgment = Object.hasOwn(state.judgments, event.post.id) ? state.judgments[event.post.id] : undefined
      return { ...next, posts: upsert(state.posts, { ...event.post, ...judgment }) }
    }
    case 'score': {
      // A replacement judgment without a rationale must not retain a rationale
      // for the previous verdict. Metadata-only post updates still preserve it.
      const judgment = { ...event.judgment, explanation: event.judgment.explanation }
      return {
        ...next, judgments: { ...state.judgments, [event.postId]: judgment },
        posts: state.posts.map(post => post.id === event.postId ? { ...post, ...judgment } : post),
      }
    }
    case 'observation': return { ...next, observations: upsert(state.observations, event.observation) }
    case 'explanation': return { ...next, explanation: { ...state.explanation, title: event.title, started: true } }
    case 'token': return { ...next, explanation: { ...state.explanation, text: state.explanation.text + event.text, started: true } }
    case 'done': return { ...next, status: 'complete' }
    case 'stopped': return { ...next, status: 'stopped' }
    case 'error': return { ...next, error: event.message, status: event.fatal ? 'failed' : state.status }
    default: return state // Unknown future kinds are ignored at runtime.
  }
}
