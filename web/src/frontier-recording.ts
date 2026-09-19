import snapshot from '../../demo/recordings/pace-the-frontier/snapshot.json'
import type { Demo } from './demo'
import type {
  Evidence,
  InvestigationEventPayload,
  PlaybackSource,
  RecordingMetadata,
  ScheduledEvent,
  TimelineBucket,
  TimelineData,
} from './investigation-state'

// Saved public source payloads, not a recording of a model or pipeline run.
// Only the presentation schedule and explicitly editorial annotations are authored.
const directory = 'demo/recordings/pace-the-frontier'
const posts = [...snapshot.posts].sort((a, b) => a.publishedAt.localeCompare(b.publishedAt))
const primary = posts.find(post => post.id === snapshot.primaryPostId)
if (!primary) throw new Error('The frontier snapshot is missing its primary post')

const primaryPost = primary
const primaryUrl = primary.url
const claim = primary.text.split('\n\n')[0]
const summary = 'These saved sources distinguish Dario’s essay announcement from older wording and the responses to it. Musk endorses Dario; Altman announces his own evaluator commitment; Hassabis supports the direction and a standards body. Sanders says pacing is insufficient, while Hwang questions evaluator independence, knowledge and funding. The earlier phrase is not established as the essay’s origin. Neither endorsements nor announced commitments prove implementation.'

export const frontierRecording: Demo = {
  id: 'frontier-recorded',
  number: '01',
  mode: 'lineage',
  sourceType: 'snapshot',
  inputAliases: [primaryUrl, 'We Must Pace the Frontier'],
  title: 'Dario’s announcement.\nThe response, in context.',
  subtitle: 'Saved source posts separate earlier wording, endorsements, commitments and criticism.',
  claim,
  anchor: 'We Must Pace the Frontier',
  headline: 'An announcement is not every response to it.',
  takeaway: 'Earlier wording, endorsement and commitment are different evidence.',
  summary,
  caveat: 'Saved source snapshot, not a recorded model or pipeline run. Selection is partial; playback timing and annotations are authored. Truncated embeds are preserved without reconstructing missing text.',
  // The source adapter below supplies captured posts, never demonstration fixtures.
  evidence: [],
}

const annotations: Record<string, { role: string; title: string; explanation: string }> = {
  '2087370436959186977': {
    role: 'Earlier phrase',
    title: 'Earlier wording, not an established origin.',
    explanation: 'Editorial annotation: roon’s August phrase predates Dario’s announcement. This snapshot does not establish it as the earliest use or as the origin of the essay.',
  },
  '2098773920774074715': {
    role: 'Author announcement · excerpt',
    title: 'The author announces the essay.',
    explanation: 'Editorial annotation: Dario announces his own essay and begins describing Anthropic’s commitment to third-party evaluator access. The saved embed is truncated; its missing tail is not reconstructed, and an announcement does not establish implementation.',
  },
  '2098789109980332057': {
    role: 'Endorsement · quotes Dario',
    title: 'An endorsement without a concrete commitment.',
    explanation: 'Editorial annotation: Musk’s “Dario is right” quotes Dario’s announcement, as confirmed by the saved quote ID. It is an endorsement, not a concrete evaluator commitment.',
  },
  '2098811563415150910': {
    role: 'Announced commitment · quotes Dario',
    title: 'Altman announces his own commitment.',
    explanation: 'Editorial annotation: Altman quotes Dario and announces that OpenAI will also give independent evaluators employee-like access. This is an announced commitment, not proof that it was implemented.',
  },
  '2098847403134611522': {
    role: 'Criticism · excerpt',
    title: 'Sanders says pacing is not enough.',
    explanation: 'Editorial annotation: Sanders’s saved excerpt says pacing is a start but not enough and uses a braking metaphor. The embed is truncated; this annotation makes no claim that its unseen tail calls for a ban or pause.',
  },
  '2098909516582490602': {
    role: 'Support for direction · quotes Dario',
    title: 'Support for direction is not the same commitment.',
    explanation: 'Editorial annotation: Hassabis quotes Dario, supports the direction of the essay and references a proposed industry-wide standards body. The saved post does not announce an embedded-evaluator commitment.',
  },
  '2099145338678378958': {
    role: 'Criticism of the evaluator tradeoff',
    title: 'Hwang questions the evaluator tradeoff.',
    explanation: 'Editorial annotation: Hwang questions whether third-party evaluators can be independent, knowledgeable and sustainably funded together. The saved payload does not prove a direct reply or quote relationship to Dario’s announcement.',
  },
}

function savedEvidence(saved: typeof posts[number]): Evidence {
  const annotation = annotations[saved.id]
  const { role: _savedRole, ...metadata } = saved
  return {
    ...metadata, capture: { ...saved.capture }, context: annotation.role,
    labelSource: 'editorial', explanation: annotation.explanation,
  }
}

function savedTimeline(): TimelineData {
  const months = new Map<string, TimelineBucket>()
  for (const post of posts) {
    const date = new Date(post.publishedAt)
    const key = post.publishedAt.slice(0, 7)
    const existing = months.get(key)
    months.set(key, {
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      count: (existing?.count ?? 0) + 1,
      coverage: 'partial',
    })
  }
  const buckets = [...months.values()]
  const latest = buckets[buckets.length - 1]
  return {
    buckets,
    provenance: 'sample',
    query: 'Selected saved posts, not X search volume',
    window: { start: posts[0].publishedAt, end: posts[posts.length - 1].publishedAt },
    preferredPeriod: { year: latest.year, month: latest.month },
  }
}

export function createFrontierRecording(runId: string): PlaybackSource {
  const recording: RecordingMetadata = {
    capturedAt: snapshot.capturedAt,
    sourceCount: posts.length,
    primaryUrl,
    essayUrl: snapshot.essayUrl,
    description: `Saved public X embed source snapshot; not a recorded model or pipeline run. ${snapshot.selection} Presentation timing and annotations are authored.`,
    limitations: [...snapshot.limitations],
    files: [
      `${directory}/snapshot.json`,
      ...posts.map(post => `${directory}/${post.capture.rawFile}`),
    ],
  }
  const events: ScheduledEvent[] = []
  let at = 0
  // Deterministic illustrative pacing; these are not captured execution times.
  const add = (payload: InvestigationEventPayload, delay = 250) => {
    events.push({ at, event: { ...payload, runId, sequence: events.length + 1 } })
    at += delay
  }

  add({ kind: 'started' })
  add({ kind: 'stage', name: 'Opening saved source posts · illustrative pacing' })
  add({ kind: 'activity', timeline: savedTimeline() })
  // The source column leads with the author's announcement; the lineage below
  // still follows publication time, including the earlier phrase.
  add({ kind: 'post', post: savedEvidence(primaryPost) }, 400)
  for (const saved of posts) {
    const annotation = annotations[saved.id]
    if (saved.id !== primaryPost.id) add({ kind: 'post', post: savedEvidence(saved) }, 400)
    add({
      kind: 'observation',
      observation: {
        id: `saved-${saved.id}`,
        date: saved.publishedAt,
        evidenceId: saved.id,
        url: saved.url,
        title: annotation.title,
        description: annotation.explanation.replace(/^Editorial annotation: /, ''),
        label: annotation.role,
      },
    }, 650)
  }
  add({ kind: 'stage', name: 'Reading the authored summary · selected sample only' })
  add({ kind: 'explanation', title: 'Editorial summary · announcement and response' })
  for (const text of summary.match(/\S+\s*/g) ?? []) {
    add({ kind: 'token', text }, Array.from(text).length * 16)
  }
  add({ kind: 'done' })
  return {
    info: { runId, claim, mode: 'lineage', provenance: 'recorded', recording },
    events,
  }
}
