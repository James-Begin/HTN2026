import { memo, useState } from 'react'
import { ArrowDownToLine, ArrowLeft, ArrowUpRight, Check, ChevronDown, Heart, Info, Pause, Play, RotateCcw, X } from 'lucide-react'
import type { Evidence, InvestigationState, Provenance, TimelineSelection, TraceMoment } from './investigation-state'
import { isTerminal } from './investigation-state'
import { tweetLink, verdictLabels } from './evidence'
import type { PlaybackControls } from './useEventPlayback'
import Dialog, { EvidenceDialog } from './Dialog'
import Timeline from './Timeline'
import StreamText from './StreamText'
import './investigation.css'

function formatDate(date?: string, includeTime = false) {
  if (!date) return 'Date not supplied'
  if (date.length === 4) return date
  if (Number.isNaN(Date.parse(date))) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC', ...(includeTime ? { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' } as const : {}) }).format(new Date(date))
}

function dateScope(date: string | undefined, selection: TimelineSelection | null) {
  if (!selection) return 'all'
  if (!date || (selection.month && date.length < 7)) return 'undated'
  const prefix = selection.month ? `${selection.year}-${String(selection.month).padStart(2, '0')}` : String(selection.year)
  return date.startsWith(prefix) ? 'match' : 'outside'
}

const Moment = memo(function Moment({ moment, evidence, scope, onInspect }: {
  moment: TraceMoment; evidence?: Evidence; scope: string; onInspect: (id: string) => void
}) {
  const link = evidence ? tweetLink(evidence) : moment.url ? tweetLink({ id: moment.id, author: '', text: moment.title, url: moment.url }) : null
  return <li className={`lineage-moment reveal-item ${scope === 'outside' ? 'outside-period' : ''} ${scope === 'match' ? 'in-period' : ''}`} data-visible="true">
    <span className="lineage-dot" />
    <div className="moment-date"><time dateTime={moment.date} title={moment.date}>{formatDate(moment.date, Boolean(evidence?.capture))}</time>{moment.label && <span>{moment.label}</span>}</div>
    <h3>{moment.title}</h3>
    <p>{moment.description}</p>
    <div className="moment-actions">{link && <a href={link.href} target="_blank" rel="noopener noreferrer">{link.label}<ArrowUpRight size={13} /></a>}{evidence && <button onClick={() => onInspect(evidence.id)} aria-label={`Inspect ${evidence.author}`}><Info size={13} />Context</button>}</div>
  </li>
})

const PostCard = memo(function PostCard({ item, scope, onInspect }: {
  item: Evidence; scope: string; onInspect: (id: string) => void
}) {
  const link = tweetLink(item)
  return <article className={`key-post reveal-item ${scope === 'outside' ? 'outside-period' : ''} ${scope === 'match' ? 'in-period' : ''}`} data-visible="true">
    <header><span className="post-avatar" aria-hidden="true">𝕏</span><div><h3>{item.author}</h3><span>{formatDate(item.publishedAt, Boolean(item.capture))}</span></div></header>
    <a className="post-text-link" href={link.href} target="_blank" rel="noopener noreferrer" aria-label={`${link.label}: ${item.author}`}><p>{item.text}</p><span className="post-destination">{link.label}<ArrowUpRight size={13} /></span></a>
    {item.capture?.textIsExcerpt && <p className="post-capture-note">X embed excerpt · truncated text</p>}
    <footer><span className={`post-relation relation-${item.verdict ?? 'pending'}`}>{item.verdict ? verdictLabels[item.verdict] : item.capture ? item.context ?? 'Saved source' : 'Not evaluated'}</span><div>{item.likes !== undefined && <span className="post-likes" title={item.capture ? `Likes captured ${item.capture.capturedAt}` : 'Recorded likes'}><Heart size={11} />{item.likes.toLocaleString('en-US')}</span>}<button className="post-context" onClick={() => onInspect(item.id)} aria-label={`Inspect ${item.author}`} title="Inspect evidence"><Info size={14} /></button></div></footer>
  </article>
})

const Posts = memo(function Posts({ posts, provenance, snapshot, selection, onInspect }: {
  posts: Evidence[]; provenance: Provenance; snapshot: boolean; selection: TimelineSelection | null; onInspect: (id: string) => void
}) {
  const [popular, setPopular] = useState(false)
  const visible = popular ? posts.filter(item => item.likes !== undefined).sort((a, b) => b.likes! - a.likes!) : posts
  return <section id="trace-posts" className="posts-space" aria-label="Key posts">
    <div className="space-heading"><h2>Key posts</h2><label className="post-selector"><span className="sr-only">Post selection</span><select aria-label="Post selection" value={popular ? 'popular' : 'key'} onChange={event => setPopular(event.target.value === 'popular')}><option value="key">All</option><option value="popular">Popular</option></select><ChevronDown size={12} /></label></div>
    <p className="space-caption">{popular ? 'By recorded likes, within these results.' : 'The anchor. The echoes. The exceptions.'}</p>
    <div className="key-posts-list">{visible.map(item => <PostCard key={item.id} item={item} scope={dateScope(item.publishedAt, selection)} onInspect={onInspect} />)}{visible.length === 0 && <p className="quiet-empty">{popular ? 'No engagement counts are available. Switch to All to see the posts.' : 'No posts received yet.'}</p>}</div>
    <p className="column-footnote">{snapshot ? 'Captured source text; editorial notes, not model predictions. Likes are a point-in-time snapshot.' : `${provenance === 'preview' ? 'Fixture labels, not truth scores.' : 'Semantic matches, not truth scores.'} Missing post IDs open an X text search.`}</p>
  </section>
})

// Data-only presentation: no Demo, fixture lookup, schedule, or elapsed clock.
// Playback is optional; a live adapter must supply its own stop semantics later.
export default function Investigation({ state, playback, onBack, onExport, onAbout }: {
  state: InvestigationState; playback?: PlaybackControls; onBack: () => void; onExport: (state: InvestigationState) => void; onAbout: () => void
}) {
  const [selection, setSelection] = useState<TimelineSelection | null>(null)
  const [inspectId, setInspectId] = useState<string | null>(null)
  const [showRecording, setShowRecording] = useState(false)
  const showAbout = () => state.recording ? setShowRecording(true) : onAbout()
  const inspect = state.posts.find(post => post.id === inspectId)
  const finished = isTerminal(state.status)
  const controls = state.provenance === 'live' ? undefined : playback
  const paused = controls ? !controls.playing : false
  const periodLabel = selection ? selection.month ? new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(selection.year, selection.month - 1, 1))) : String(selection.year) : null
  const matchingMoments = selection ? state.observations.filter(moment => dateScope(moment.date, selection) === 'match').length : state.observations.length
  const provenanceLabel = state.recording ? 'Saved X snapshot' : state.provenance === 'preview' ? 'Simulated example' : state.provenance === 'recorded' ? 'Recorded run' : 'Live investigation'
  const status = state.status === 'complete' ? (state.recording ? 'Snapshot replay complete' : state.provenance === 'preview' ? 'Example complete' : 'Investigation complete')
    : state.status === 'failed' ? 'Investigation failed' : state.status === 'stopped' ? 'Investigation stopped'
      : paused ? 'Paused' : state.stage ?? 'Starting investigation'

  return <div className={`trace-workspace ${!paused && !finished ? 'is-playing' : 'is-paused'}`}>
    <header className="trace-intro"><div><div className="trace-kicker"><button onClick={onBack}><ArrowLeft size={12} />Examples</button><span>/</span><span>{state.mode === 'lineage' ? 'Trace history' : state.mode === 'verify' ? 'Check corroboration' : 'Resolve a post'}</span><button className="demo-label" onClick={showAbout}>{provenanceLabel}<Info size={11} /></button></div><h1>{state.claim.startsWith('https://x.com/') ? <a href={state.claim} target="_blank" rel="noopener noreferrer" title="Open post on X">{state.claim}<ArrowUpRight size={16} /></a> : state.claim}</h1></div><button className="icon-button trace-export" onClick={() => onExport(state)} aria-label={state.provenance === 'preview' ? 'Export example' : 'Export investigation'} title="Export investigation"><ArrowDownToLine size={17} /></button></header>

    <nav className="space-jump" aria-label="Investigation sections"><a href="#trace-timeline">Timeline</a><a href="#trace-lineage">Lineage</a><a href="#trace-posts">Key posts</a></nav>
    <div className="three-spaces">
      <Timeline data={state.timeline} selection={selection} onSelect={setSelection} />
      <section id="trace-lineage" className="lineage-space" aria-label="Claim lineage">
        <div className="space-heading"><h2>Lineage</h2><span className="lineage-count">{state.observations.length.toString().padStart(2, '0')} observations</span></div>
        <p className="space-caption">{state.recording ? 'Saved chronology. Editorial notes—not proof of copying.' : 'A trail of evidence. Not proof of copying.'}</p>
        <div className="period-focus" role="status">{periodLabel ? <><span>{periodLabel} · {matchingMoments ? 'dated observations highlighted' : 'no saved dated observations'}</span><button onClick={() => setSelection(null)} aria-label="Clear date focus"><X size={12} /></button></> : <span>Click a period on the timeline to focus the trail.</span>}</div>
        <ol className="lineage-thread">{state.observations.map(moment => <Moment key={moment.id} moment={moment} evidence={state.posts.find(item => item.id === moment.evidenceId)} scope={dateScope(moment.date, selection)} onInspect={setInspectId} />)}</ol>
        {state.explanation.started && <section className="lineage-context reveal-item" data-visible="true" aria-label={state.recording ? 'Editorial explanation' : state.provenance === 'preview' ? 'Curated explanation' : 'Explanation'}><span className="context-label">{state.recording ? 'Editorial context · not model-generated' : 'In context'}</span>{state.explanation.title && <h3>{state.explanation.title}</h3>}<StreamText text={state.explanation.text} paused={paused} finished={finished} /></section>}
        {state.error && <p className="quiet-empty" role="status">{state.error}</p>}
        <p className="column-footnote">Undated references remain visible when a period is selected.</p>
      </section>
      <Posts posts={state.posts} provenance={state.provenance} snapshot={Boolean(state.recording)} selection={selection} onInspect={setInspectId} />
    </div>

    <footer className="trace-bottom"><div className="trace-status" role="status"><span className="status-dot" />{status}</div><div className="trace-controls">{controls && (finished ? <button onClick={controls.replay}><RotateCcw size={13} />Replay</button> : <><button onClick={controls.toggle} aria-label={controls.playing ? 'Pause playback' : 'Resume playback'}>{controls.playing ? <Pause size={13} /> : <Play size={13} />}{controls.playing ? 'Pause' : 'Resume'}</button><button onClick={controls.finish} aria-label="Skip animation"><Check size={13} />Show all</button></>)}<button onClick={showAbout} className="trace-data-note">About the data<Info size={12} /></button></div></footer>
    {inspect && <EvidenceDialog item={inspect} onClose={() => setInspectId(null)} />}
    {showRecording && state.recording && <Dialog title="About this saved snapshot" onClose={() => setShowRecording(false)}>
      <p className="modal-intro">Real source payloads, saved for offline replay. This is not a recording of a production investigation.</p>
      <div className="capture-details"><p><strong>Capture completed:</strong> <time dateTime={state.recording.capturedAt}>{state.recording.capturedAt}</time></p><p><strong>Saved sources:</strong> {state.recording.sourceCount}</p><p>{state.recording.description}</p></div>
      <ul className="snapshot-limitations">{state.recording.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
      <div className="snapshot-source-links"><a href={state.recording.primaryUrl} target="_blank" rel="noopener noreferrer">Dario’s announcement on X <ArrowUpRight size={13} /></a><a href={state.recording.essayUrl} target="_blank" rel="noopener noreferrer">The original essay <ArrowUpRight size={13} /></a></div>
      <p className="modal-small">The snapshot and replay are bundled locally. Following source links requires internet access; playing the saved example does not.</p>
    </Dialog>}
  </div>
}
