import { traceMoments } from './demo'
import type { Demo } from './demo'
import type { InvestigationEventPayload, PlaybackSource, TimelineData } from './investigation-state'

// Invented visual fixtures, not measured counts or a recording. Keep all example
// generation here; timeline and investigation components never select a profile.
const BASELINES: Record<string, readonly number[]> = {
  frontier: [0, 0, 0, 1, 0, 2, 3, 4, 6, 9, 12, 18, 24, 38, 54, 92, 180, 420, 1100, 2900, 4700],
  ssi: [0, 0, 0, 0, 1, 0, 2, 1, 3, 4, 5, 6, 9, 12, 18, 24, 41, 85, 1600, 3900, 5800],
  covfefe: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1200],
}
const MONTH_WEIGHTS = [0.42, 0.51, 0.68, 0.61, 0.84, 0.73, 0.91, 1.08, 0.98, 1.27, 1.56, 1.34]

function illustrativeTimeline(demo: Demo): TimelineData {
  const baselines = BASELINES[demo.id]
  if (!baselines) throw new Error(`No illustrative timeline for ${demo.id}`)
  return {
    provenance: 'illustrative', query: demo.anchor,
    preferredPeriod: { year: 2006 + baselines.length - 1, month: demo.id === 'covfefe' ? 5 : 9 },
    buckets: baselines.flatMap((baseline, index) => MONTH_WEIGHTS.map((weight, monthIndex) => ({
      year: 2006 + index, month: monthIndex + 1, coverage: 'complete' as const,
      count: demo.id === 'covfefe' && index === 11
        ? [0, 0, 0, 0, 18400, 6300, 1900, 920, 580, 420, 310, 240][monthIndex]
        : Math.round(baseline * weight),
    }))),
  }
}

// Schedule is an adapter concern, never a rendering rule. These normalized events
// are synthetic even when their source text/metadata came from historical fixtures.
export function createDemoPlayback(demo: Demo, runId: string): PlaybackSource {
  const moments = traceMoments[demo.id] ?? []
  const scheduled: { at: number; payload: InvestigationEventPayload }[] = []
  const add = (at: number, payload: InvestigationEventPayload) => scheduled.push({ at, payload })
  add(0, { kind: 'started' })
  add(0, { kind: 'stage', name: 'Following the evidence' })
  add(0, { kind: 'activity', timeline: illustrativeTimeline(demo) })
  moments.forEach((observation, index) => add(450 + index * 1250, { kind: 'observation', observation }))
  demo.evidence.forEach((item, index) => {
    const { verdict, explanation, ...post } = item
    const at = 1150 + index * 1450
    add(at, { kind: 'post', post })
    add(at + 200, { kind: 'score', postId: post.id, judgment: { verdict, explanation, labelSource: 'fixture' } })
  })
  const summaryStart = 1100 + moments.length * 1250
  add(summaryStart, { kind: 'stage', name: 'Putting the evidence in context' })
  add(summaryStart, { kind: 'explanation', title: demo.takeaway })
  let offset = 0
  for (const text of demo.summary.match(/\S+\s*/g) ?? []) {
    add(summaryStart + offset * 24, { kind: 'token', text })
    offset += Array.from(text).length
  }
  add(summaryStart + offset * 24 + 300, { kind: 'done' })
  return {
    info: { runId, claim: demo.claim, mode: demo.mode, provenance: 'preview' },
    events: scheduled.sort((a, b) => a.at - b.at).map(({ at, payload }, index) => ({
      at, event: { ...payload, runId, sequence: index + 1 },
    })),
  }
}
