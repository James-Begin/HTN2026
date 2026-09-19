import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowLeft, ArrowRight, ArrowUpRight, BarChart3, Check, Clock3, Heart, Info, Link2, Search, Sparkles, X } from 'lucide-react'
import snapshot from '../../demo/recordings/pace-the-frontier/snapshot.json'
import liveCapture from '../../demo/recordings/sequitor-live.json'
import wetLabCapture from '../../demo/recordings/anthropic-wet-lab.json'
import darioHumorCapture from '../../demo/recordings/dario-humor.json'
import storyCapture from '../../demo/recordings/sequitor-story.json'
import Neighborhood from './Neighborhood'
import type { GraphPost, SemanticEdge, StoryAnnotation } from './graphData'
import './sequitor.css'

type Post = {
  id: string; text: string; publishedAt: string; author: string; handle?: string
  avatar?: string; likes?: number | null; reposts?: number | null; replies?: number | null
  url?: string; parentId?: string | null; quotedPostId?: string | null
  scope?: string; captureTime?: string; textIsExcerpt?: boolean
  basetenKind?: string; sameClaimScore?: number; sameClaimRegister?: string
  basetenPick?: boolean; semanticScore?: number; lexicalScore?: number
  rankingScore?: number; rankingMethod?: string
}
type Bucket = { day: string; count: number; coverage: 'complete' | 'partial' | 'sample'; pending?: boolean }
type ActivityScale = 'day' | 'hour' | 'month'
type ActivityResult = { granularity: 'hour'; day: string; query: string; buckets: Bucket[]; xSpend: number }
type Run = {
  id: string; seed: string; title: string; kind: 'live' | 'saved'; capturedAt?: string
  scope: string; query?: string | null; buckets: Bucket[]; posts: Post[]; selectedDay: string
  rankingCoverage: string; searchPlan?: { contextLabel?: string; entities?: string[]; angles?: string[]; uncertainties?: string[]; volumePhrase?: string; volumeFallback?: string; discoveryPhrase?: string | null; discoveryQueries?: string[]; expansionQueries?: string[]; expansionReason?: string; whyDiscovery?: string; model?: string | null; error?: string } | null
  model?: { openai?: string | null; baseten?: { status?: string; model?: string | null; classified?: number; retrieval?: { status?: string; semantic?: string; reranker?: string } } | string }
  note: string; xSpend?: number
  savedPeriods?: Record<string, PeriodResult>
  streamSource?: 'live' | 'cache' | 'recorded'
  activityScaleMax?: number
  seedPost?: Post
}
type PeriodResult = { day: string; posts: Post[]; rankingCoverage: string; partial: boolean; xSpend: number; model: Run['model'] }
type StreamEvent = { runId: string; sequence: number; type: string; payload: Record<string, unknown> }
type StartedRun = { runId: string; eventsUrl: string }
type XWidgets = { widgets: { createTweet: (id: string, element: HTMLElement, options: Record<string, string | boolean>) => Promise<HTMLElement | null> } }
declare global { interface Window { twttr?: XWidgets } }
let widgetsLoad: Promise<XWidgets> | null = null

function loadXWidgets(): Promise<XWidgets> {
  if (window.twttr?.widgets) return Promise.resolve(window.twttr)
  if (!widgetsLoad) widgetsLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://platform.twitter.com/widgets.js'
    script.async = true
    script.onload = () => window.twttr?.widgets ? resolve(window.twttr) : reject(new Error('X widgets unavailable'))
    script.onerror = () => reject(new Error('X widgets unavailable'))
    document.head.appendChild(script)
  })
  return widgetsLoad
}

function mergePosts(existing: Post[], incoming: Post[]): Post[] {
  const positions = new Map(existing.map((post, index) => [post.id, index]))
  const merged = [...existing]
  for (const post of incoming) {
    const index = positions.get(post.id)
    if (index === undefined) {
      positions.set(post.id, merged.length)
      merged.push(post)
    } else merged[index] = { ...merged[index], ...post }
  }
  return merged
}

const defaultSeed = 'https://x.com/DarioAmodei/status/2098773920774074715'
const sourcePosts: Post[] = snapshot.posts.map(post => ({
  id: post.id, text: post.text, publishedAt: post.publishedAt, author: post.author,
  handle: post.handle, likes: post.likes, url: post.url,
  quotedPostId: 'quotedPostId' in post ? post.quotedPostId : null,
  scope: 'saved source', captureTime: post.capture.capturedAt,
  textIsExcerpt: post.capture.textIsExcerpt,
}))
const sourceDays = [...new Set(sourcePosts.map(post => post.publishedAt.slice(0, 10)))].sort()
const sevenPostFallback: Run = {
  id: 'frontier-saved', seed: defaultSeed, title: 'We Must Pace the Frontier', kind: 'saved',
  capturedAt: snapshot.capturedAt, scope: 'Seven selected saved X posts', query: null,
  buckets: sourceDays.map(day => ({ day, count: sourcePosts.filter(post => post.publishedAt.startsWith(day)).length, coverage: 'sample' })),
  posts: sourcePosts, selectedDay: '2026-09-12', rankingCoverage: 'selected saved sources only',
  searchPlan: null, model: { openai: 'not run in saved sample', baseten: 'not run in saved sample' },
  note: 'This is a selected source sample. Its bar heights count saved posts, not X-wide activity.', xSpend: 0,
}
const darioHumorPosts: Post[] = darioHumorCapture.posts as Post[]
function withDarioHumor(run: Run): Run {
  const savedPeriods = Object.fromEntries(Object.entries(run.savedPeriods || {}).map(([day, period]) =>
    [day, { ...period, posts: mergePosts(period.posts, darioHumorPosts.filter(post => post.publishedAt.startsWith(day))) }]))
  return { ...run,
    posts: mergePosts(run.posts, darioHumorPosts.filter(post => post.publishedAt.startsWith(run.selectedDay))),
    savedPeriods,
    note: `${run.note} Three later targeted humor-search posts are included with their own capture timestamps.`,
  }
}
function hydrateRecordedContext(run: Run): Run {
  if (run.searchPlan?.contextLabel || !run.searchPlan?.discoveryPhrase) return run
  return { ...run, searchPlan: {
    ...run.searchPlan,
    contextLabel: 'AI-industry slowdown discussion',
    entities: ['Anthropic', 'AI industry'],
    angles: ['frontier pacing', 'independent evaluation'],
    uncertainties: ['The recorded post and its retrieved responses do not establish influence, provenance, or factual accuracy.'],
    discoveryQueries: [run.searchPlan.discoveryPhrase],
    expansionQueries: [],
  } }
}
const fallback: Run = {
  ...withDarioHumor(hydrateRecordedContext(liveCapture as Run)), kind: 'saved',
  scope: 'Recorded X counts and retrieved posts',
  note: `Saved run captured ${formatTime(liveCapture.capturedAt)}. Its bars were measured on X at capture time; post lists cover retrieved candidates only. Three humor-search posts were added later with separate capture timestamps.`,
}
const wetLab: Run = wetLabCapture as Run
const recordedReferencePosts: GraphPost[] = [...new Map([
  ...fallback.posts,
  ...Object.values(fallback.savedPeriods || {}).flatMap(period => period.posts),
  ...(fallback.seedPost ? [fallback.seedPost] : []),
].map(post => [post.id, post])).values()]

function pendingActivity(run: Run): Run {
  return { ...run, activityScaleMax: Math.max(1, ...run.buckets.map(bucket => bucket.count)),
    buckets: run.buckets.map(bucket => ({ ...bucket, count: 0, pending: true })) }
}

function formatDay(day: string, withYear = true) {
  const date = new Date(`${day}T12:00:00Z`)
  return new Intl.DateTimeFormat('en-CA', { day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC' }).format(date)
}
function formatTime(iso: string) {
  if (!iso || Number.isNaN(Date.parse(iso))) return 'Time unavailable'
  return new Intl.DateTimeFormat('en-CA', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto', timeZoneName: 'short' }).format(new Date(iso))
}
function shortNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Intl.NumberFormat('en', { notation: value >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value)
}
function activityAnnotation(post: Post): StoryAnnotation {
  const kind = (post.basetenKind || '').toLowerCase()
  if (post.scope === 'seed') return { role: 'announcement', focus: 'starting post' }
  if (post.scope === 'humor branch' || /joke|humou?r|meme|riff/.test(kind)) return { role: 'humor', focus: 'humor or riff' }
  if (/criticism|critique|skeptic/.test(kind)) return { role: 'critique', focus: 'critical response' }
  if (/question|ask/.test(kind)) return { role: 'question', focus: 'question or uncertainty' }
  if (/same wording|report|explanation/.test(kind) || post.scope === 'wet-lab context' || post.scope === 'broader discovery') return { role: 'reporting', focus: 'event framing' }
  if (/reaction|response/.test(kind) || post.scope === 'direct conversation') return { role: 'adoption', focus: 'response' }
  if (post.scope === 'context expansion') return { role: 'explanation', focus: 'context expansion' }
  return { role: 'other', focus: 'not yet classified' }
}
function inferredAnnotations(posts: Post[]): Record<string, StoryAnnotation> {
  return Object.fromEntries(posts.map(post => [post.id, activityAnnotation(post)]))
}
function aggregateMonths(buckets: Bucket[]): Bucket[] {
  const months = new Map<string, Bucket>()
  for (const bucket of buckets) {
    const month = bucket.day.slice(0, 7)
    const prior = months.get(month)
    months.set(month, { day: `${month}-01`, count: (prior?.count || 0) + bucket.count,
      coverage: bucket.coverage === 'partial' || prior?.coverage === 'partial' ? 'partial' : bucket.coverage,
      pending: bucket.pending || prior?.pending })
  }
  return [...months.values()]
}
function sampleHourly(posts: Post[], selectedDay: string): Bucket[] {
  const hours = new Map<string, Bucket>()
  for (const post of posts.filter(item => item.publishedAt?.startsWith(selectedDay))) {
    const hour = post.publishedAt.slice(0, 13) + ':00:00Z'
    const prior = hours.get(hour)
    hours.set(hour, { day: hour, count: (prior?.count || 0) + 1, coverage: 'sample' })
  }
  return [...hours.values()].sort((left, right) => left.day.localeCompare(right.day))
}
function activityLabel(value: string, scale: ActivityScale) {
  if (scale === 'hour') return new Intl.DateTimeFormat('en-CA', { hour: 'numeric', timeZone: 'UTC' }).format(new Date(value)) + ' UTC'
  if (scale === 'month') return new Intl.DateTimeFormat('en-CA', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value))
  return formatDay(value)
}
async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || 'Could not load the data')
  return data as T
}

function Wordmark() {
  return <span className="seq-wordmark"><span className="seq-mark" aria-hidden="true"><i /><i /><i /></span>sequitor<span className="seq-wordmark-dot">.</span></span>
}

function Timeline({ buckets, selectedDay, onSelect, kind, scaleMax, contextQuery, scale, onScaleChange, loading }: { buckets: Bucket[]; selectedDay: string; onSelect: (day: string) => void; kind: Run['kind']; scaleMax?: number; contextQuery?: string; scale: ActivityScale; onScaleChange: (scale: ActivityScale) => void; loading?: boolean }) {
  const max = Math.max(1, scaleMax || 0, ...buckets.map(bucket => bucket.count))
  const selected = scale === 'day' ? buckets.find(bucket => bucket.day === selectedDay) : undefined
  const total = scale === 'day' ? selected?.count : buckets.reduce((sum, bucket) => sum + bucket.count, 0)
  const isSample = buckets.some(bucket => bucket.coverage === 'sample')
  return <section className="seq-timeline" aria-label="Activity over time">
    <div className="seq-section-top"><div><h2>Activity over time</h2><p>{isSample ? 'Selected saved posts' : contextQuery ? `X posts matching ${contextQuery}` : 'X posts matching the measured phrase'}</p></div><BarChart3 size={18} aria-hidden="true" /></div>
    <div className="seq-activity-scale" role="group" aria-label="Activity resolution">{(['day', 'hour', 'month'] as const).map(value => <button key={value} type="button" className={scale === value ? 'active' : ''} aria-pressed={scale === value} onClick={() => onScaleChange(value)}>{value === 'day' ? 'Daily' : value === 'hour' ? 'Hourly' : 'Monthly'}</button>)}</div>
    <div className="seq-activity-total"><strong>{loading || selected?.pending ? '—' : shortNumber(total)}</strong><span>{scale === 'hour' ? `posts across ${formatDay(selectedDay)} by hour` : scale === 'month' ? 'posts in the captured months' : <>posts on {formatDay(selectedDay)} <span className="seq-utc">UTC</span></>}</span></div>
    <div className="seq-chart" role="group" aria-label={scale === 'day' ? 'Choose a day' : `${scale} activity`}>
      {buckets.map(bucket => <button key={bucket.day} type="button" className={`seq-bar ${scale === 'day' && bucket.day === selectedDay ? 'is-selected' : ''} ${bucket.coverage !== 'complete' ? 'is-partial' : ''} ${bucket.pending ? 'is-pending' : ''}`}
        style={{ height: '100%', transform: `scaleY(${bucket.pending ? 0 : Math.max(.09, Math.sqrt(bucket.count / max))})` }}
        title={bucket.pending ? `${activityLabel(bucket.day, scale)}: awaiting count` : `${activityLabel(bucket.day, scale)}: ${bucket.count.toLocaleString()} ${bucket.coverage === 'sample' ? 'saved' : 'matching'} posts`}
        aria-label={bucket.pending ? `${activityLabel(bucket.day, scale)}: awaiting count` : `${activityLabel(bucket.day, scale)}: ${bucket.count.toLocaleString()} ${bucket.coverage === 'sample' ? 'saved' : 'matching'} posts`}
        aria-pressed={scale === 'day' && bucket.day === selectedDay} disabled={bucket.pending || scale !== 'day'} onClick={() => onSelect(bucket.day)}><span className="sr-only">{activityLabel(bucket.day, scale)}</span></button>)}
    </div>
    <div className="seq-chart-axis"><span>{buckets.length ? activityLabel(buckets[0].day, scale) : ''}</span><span>{buckets.length ? activityLabel(buckets[buckets.length - 1].day, scale) : ''}</span></div>
    <p className="seq-timeline-foot">{isSample ? 'Sample counts · not platform activity' : `${contextQuery ? 'One context query' : 'One exact phrase'} · retweets included · ${kind === 'saved' ? 'saved measurement' : 'live measurement'}`}{scale === 'hour' ? isSample ? ' · saved post timestamps by hour' : ' · hourly count request for selected day' : scale === 'month' ? ' · monthly roll-up of daily counts' : ''}{selected?.coverage === 'partial' ? ' · partial coverage' : ''}</p>
  </section>
}

function ContextCard({ plan }: { plan?: Run['searchPlan'] }) {
  if (!plan?.contextLabel) return null
  const queries = [...(plan.discoveryQueries || []), ...(plan.expansionQueries || [])]
  return <section className="seq-context-card" aria-label="Investigation context">
    <p>OPENAI CONTEXT CARD</p><h3>{plan.contextLabel}</h3>
    {plan.entities?.length ? <div><span>Entities</span><p>{plan.entities.join(' · ')}</p></div> : null}
    {plan.volumeFallback && <div><span>Measured context query</span><p><code>{plan.volumeFallback}</code></p></div>}
    {queries.length ? <div><span>Discovery branches</span><p>{queries.map(query => <code key={query}>{query}</code>)}</p></div> : null}
    {plan.expansionReason && <small>Second pass: {plan.expansionReason}</small>}
    {plan.uncertainties?.[0] && <small>Limit: {plan.uncertainties[0]}</small>}
  </section>
}

function PostRow({ post, onOpen }: { post: Post; onOpen: (post: Post) => void }) {
  const displayAuthor = post.author.replace(/\s*·\s*@\S+$/, '')
  const showHandle = post.handle && displayAuthor.toLowerCase() !== `@${post.handle}`.toLowerCase()
  const initials = displayAuthor.replace(/^@/, '').slice(0, 2).toUpperCase()
  return <article className="seq-post">
    <button className="seq-avatar" onClick={() => onOpen(post)} aria-label={`Open context for ${post.author}`}><span aria-hidden="true">{initials}</span>{post.avatar && <img src={post.avatar} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} />}</button>
    <div className="seq-post-body">
      <div className="seq-post-head"><div><strong>{displayAuthor}</strong>{showHandle && <span>@{post.handle}</span>}</div><time dateTime={post.publishedAt}>{formatTime(post.publishedAt)}</time></div>
      <p className="seq-post-text">{post.text}</p>
      {post.textIsExcerpt && <span className="seq-post-notice">Captured excerpt; full text unavailable here</span>}
      <div className="seq-post-foot">
        <span>{post.scope === 'broader discovery' ? <><Sparkles size={12} /> Related search</> : post.scope === 'humor branch' ? <><Sparkles size={12} /> Humor search</> : post.scope === 'context expansion' ? <><Sparkles size={12} /> Context branch</> : post.scope === 'direct conversation' ? 'Direct reply or thread' : post.scope === 'saved source' ? 'Saved source' : post.scope === 'seed' ? 'Starting post' : null}</span>
        <div>{post.rankingScore !== undefined && <span className="seq-rank-score" title={`${post.rankingMethod || 'Hybrid'} score. This is a retrieval signal, not a truth or influence score.`}>Match {Math.round(post.rankingScore * 100)}</span>}{post.likes !== undefined && post.likes !== null && <span title={`Likes captured ${post.captureTime || 'when retrieved'}`}><Heart size={14} /> {shortNumber(post.likes)}</span>}
          <button onClick={() => onOpen(post)}>Context <ArrowRight size={13} /></button>
          {post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${post.author}'s post on X`}><ArrowUpRight size={16} /></a>}</div>
      </div>
    </div>
  </article>
}

function TweetEmbed({ post }: { post: Post }) {
  const holder = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  useEffect(() => {
    if (!/^\d+$/.test(post.id) || !holder.current) { setState('unavailable'); return }
    let active = true
    const node = holder.current
    node.replaceChildren()
    setState('loading')
    const timeout = window.setTimeout(() => { if (active) setState('unavailable') }, 8000)
    loadXWidgets().then(widgets => widgets.widgets.createTweet(post.id, node,
      { theme: 'dark', dnt: true, conversation: 'none', align: 'center' }))
      .then(result => { if (active) setState(result ? 'ready' : 'unavailable') })
      .catch(() => { if (active) setState('unavailable') })
      .finally(() => window.clearTimeout(timeout))
    return () => { active = false; window.clearTimeout(timeout); node.replaceChildren() }
  }, [post.id])
  return <section className={`seq-embed seq-embed-${state}`} aria-label="Official X post">
    <div className="seq-embed-label">POST ON X <span>{state === 'loading' ? 'Loading original…' : state === 'unavailable' ? 'Original preview unavailable' : 'Original preview'}</span></div>
    <div ref={holder} className="seq-embed-host" />
    {state === 'unavailable' && <p>The source card above remains available. <a href={post.url || `https://x.com/i/status/${post.id}`} target="_blank" rel="noopener noreferrer">Open on X <ArrowUpRight size={13} /></a></p>}
  </section>
}

function Context({ post, posts, onClose }: { post: Post; posts: Post[]; onClose: () => void }) {
  const relationId = post.quotedPostId || post.parentId
  const [related, setRelated] = useState<Post | null>(posts.find(item => item.id === relationId) || null)
  useEffect(() => {
    setRelated(posts.find(item => item.id === relationId) || null)
    if (relationId && !posts.some(item => item.id === relationId)) {
      getJson<Post>(`/api/context?id=${encodeURIComponent(relationId)}`).then(setRelated).catch(() => {})
    }
  }, [relationId, posts])
  return <div className="seq-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <aside className="seq-drawer" aria-label="Post context"><div className="seq-drawer-head"><button onClick={onClose}><ArrowLeft size={16} /> Back</button><h2>Post context</h2><button className="seq-icon" onClick={onClose} aria-label="Close context"><X size={18} /></button></div>
      <div className="seq-drawer-content"><p className="seq-drawer-label">SELECTED POST</p><PostRow post={post} onOpen={() => {}} />
        <TweetEmbed post={post} />
        {relationId && <section className="seq-relationship"><div className="seq-relationship-line" /><p className="seq-drawer-label">{post.quotedPostId ? 'QUOTES' : 'REPLIES TO'}</p>
          {related ? <PostRow post={related} onOpen={() => {}} /> : <a href={`https://x.com/i/status/${relationId}`} target="_blank" rel="noopener noreferrer">Open referenced post on X <ArrowUpRight size={15} /></a>}</section>}
        {!relationId && <p className="seq-context-empty">No quote or reply relationship is recorded for this post. A shared topic does not establish who saw or copied whom.</p>}
        {post.basetenKind && <p className="seq-context-model">Baseten grouped this as “{post.basetenKind}.” This is a model suggestion, not a statement of fact.</p>}
        {post.url && <a className="seq-source-link" href={post.url} target="_blank" rel="noopener noreferrer">View original post on X <ArrowUpRight size={15} /></a>}
      </div>
    </aside>
  </div>
}

export default function Sequitor() {
  const [run, setRun] = useState<Run>(fallback)
  const [seed, setSeed] = useState('')
  const [selectedDay, setSelectedDay] = useState(fallback.selectedDay)
  const [periodPosts, setPeriodPosts] = useState<Post[]>(fallback.posts)
  const [rankingCoverage, setRankingCoverage] = useState(fallback.rankingCoverage)
  const [sort, setSort] = useState<'relevance' | 'popular' | 'recent'>('relevance')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [inspect, setInspect] = useState<Post | null>(null)
  const [showData, setShowData] = useState(false)
  const [view, setView] = useState<'feed' | 'network'>('feed')
  const [health, setHealth] = useState<boolean | null>(null)
  const [activityScale, setActivityScale] = useState<ActivityScale>('day')
  const [hourlyBuckets, setHourlyBuckets] = useState<Bucket[] | null>(null)
  const [activityLoading, setActivityLoading] = useState(false)
  const requestId = useRef(0)
  const streamRef = useRef<EventSource | null>(null)
  const streamRunId = useRef<string | null>(null)
  const replayTimer = useRef<number | null>(null)
  const postQueue = useRef<Post[]>([])
  const postQueueTimer = useRef<number | null>(null)
  const pendingCompletion = useRef<Record<string, unknown> | null>(null)
  const lastSequence = useRef(0)

  useEffect(() => () => {
    streamRef.current?.close()
    if (replayTimer.current !== null) window.clearInterval(replayTimer.current)
    if (postQueueTimer.current !== null) window.clearTimeout(postQueueTimer.current)
  }, [])

  useEffect(() => {
    const sections = document.querySelectorAll<HTMLElement>('.seq-reveal')
    if (!('IntersectionObserver' in window)) { sections.forEach(section => section.classList.add('is-visible')); return }
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible')
        observer.unobserve(entry.target)
      }
    }), { threshold: 0.08 })
    sections.forEach(section => observer.observe(section))
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (activityScale !== 'hour' || run.kind === 'saved' || run.id.startsWith('pending-')) return
    let active = true
    setHourlyBuckets(null)
    setActivityLoading(true)
    getJson<ActivityResult>(`/api/activity?run=${encodeURIComponent(run.id)}&day=${encodeURIComponent(selectedDay)}&granularity=hour`)
      .then(result => {
        if (!active) return
        setHourlyBuckets(result.buckets)
        setRun(previous => ({ ...previous, xSpend: result.xSpend }))
      })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : 'Could not measure hourly activity') })
      .finally(() => { if (active) setActivityLoading(false) })
    return () => { active = false }
  }, [activityScale, run.id, run.kind, selectedDay])

  useEffect(() => {
    getJson<Run>('/api/demo').then(demo => { const recorded = hydrateRecordedContext(demo); if (requestId.current === 0) { setRun(recorded); setSelectedDay(recorded.selectedDay); setPeriodPosts(recorded.posts); setRankingCoverage(recorded.rankingCoverage) } setHealth(true) })
      .catch(() => setHealth(false))
  }, [])

  function stopCurrent() {
    streamRef.current?.close()
    streamRef.current = null
    if (replayTimer.current !== null) window.clearInterval(replayTimer.current)
    replayTimer.current = null
    if (postQueueTimer.current !== null) window.clearTimeout(postQueueTimer.current)
    postQueueTimer.current = null
    postQueue.current = []
    pendingCompletion.current = null
    if (streamRunId.current) {
      fetch(`/api/runs/${streamRunId.current}/cancel`, { method: 'POST' }).catch(() => {})
      streamRunId.current = null
    }
  }

  function completeStream(payload: Record<string, unknown>) {
    setRun(previous => ({ ...previous, model: payload.model as Run['model'] || previous.model,
      xSpend: typeof payload.xSpend === 'number' ? payload.xSpend : previous.xSpend,
      ...(previous.streamSource === 'recorded' && previous.id === fallback.id
        ? { posts: fallback.posts, savedPeriods: fallback.savedPeriods, buckets: fallback.buckets } : {}) }))
    setRankingCoverage(String(payload.rankingCoverage || 'Retrieved posts'))
    setBusy('')
    streamRef.current?.close()
    streamRunId.current = null
  }

  function drainPostQueue(id: number) {
    if (id !== requestId.current) return
    const queue = postQueue.current
    if (!queue.length) {
      postQueueTimer.current = null
      if (pendingCompletion.current) {
        const payload = pendingCompletion.current
        pendingCompletion.current = null
        completeStream(payload)
      }
      return
    }
    // The server can return whole X pages in the same event-loop turn. Paint a
    // few at a time so the feed and the map visibly grow instead of jumping.
    const amount = queue.length > 72 ? 3 : queue.length > 28 ? 2 : 1
    const next = queue.splice(0, amount)
    setPeriodPosts(previous => mergePosts(previous, next))
    postQueueTimer.current = window.setTimeout(() => drainPostQueue(id), 145)
  }

  function queueStreamPosts(posts: Post[], id: number) {
    const queue = postQueue.current
    for (const post of posts) {
      const index = queue.findIndex(item => item.id === post.id)
      if (index === -1) queue.push(post)
      else queue[index] = { ...queue[index], ...post }
    }
    if (postQueueTimer.current === null) drainPostQueue(id)
  }

  function replayExample() {
    if (health === true) { void startStreaming(defaultSeed, 'recorded'); return }
    const id = ++requestId.current
    stopCurrent()
    const recorded = { ...pendingActivity(fallback), posts: [], savedPeriods: undefined, streamSource: 'recorded' as const }
    setRun(recorded)
    setSelectedDay(recorded.selectedDay)
    setPeriodPosts([])
    setActivityScale('day')
    setHourlyBuckets(null)
    setRankingCoverage('Recorded posts arriving…')
    setBusy('Replaying the recorded investigation…')
    setError('')
    const posts = [...fallback.posts].sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1))
    let index = 0
    let tick = 0
    replayTimer.current = window.setInterval(() => {
      if (id !== requestId.current) return
      const bucket = fallback.buckets[tick]
      if (bucket) setRun(previous => ({ ...previous, buckets: previous.buckets.map(item => item.day === bucket.day ? bucket : item) }))
      // A recorded replay should feel like a retrieval session: the first
      // evidence arrives one post at a time, then the map fills in faster.
      const amount = index < 12 ? 1 : index < 48 ? 2 : 4
      const batch = posts.slice(index, index + amount)
      index += batch.length
      tick += 1
      setPeriodPosts(previous => mergePosts(previous, batch))
      if (index >= posts.length && tick >= fallback.buckets.length) {
        if (replayTimer.current !== null) window.clearInterval(replayTimer.current)
        replayTimer.current = null
        setRun(previous => ({ ...previous, posts: fallback.posts, savedPeriods: fallback.savedPeriods, buckets: fallback.buckets }))
        setRankingCoverage(fallback.rankingCoverage)
        setBusy('')
      }
    }, 170)
  }

  function openWetLabTest() {
    ++requestId.current
    stopCurrent()
    setRun(wetLab)
    setSeed(wetLab.seed)
    setSelectedDay(wetLab.selectedDay)
    setPeriodPosts(wetLab.posts)
    setRankingCoverage(wetLab.rankingCoverage)
    setSort('recent')
    setActivityScale('day')
    setHourlyBuckets(null)
    setView('feed')
    setBusy('')
    setError('')
  }

  async function explore(event?: FormEvent) {
    event?.preventDefault()
    await startStreaming(seed.trim() || defaultSeed, 'live')
  }

  async function startStreaming(seedInput: string, mode: 'live' | 'recorded') {
    const id = ++requestId.current
    stopCurrent()
    lastSequence.current = 0
    setRun({ ...fallback, id: `pending-${id}`, seed: seedInput,
      title: mode === 'recorded' ? fallback.title : seedInput || 'Starting investigation',
      kind: mode === 'recorded' ? 'saved' : 'live', buckets: [], posts: [],
      savedPeriods: undefined, streamSource: mode, model: undefined,
      note: mode === 'recorded' ? fallback.note : 'The measured scope and retrieved posts will appear as they arrive.',
      rankingCoverage: 'Posts will appear as they arrive' })
    setPeriodPosts([])
    setActivityScale('day')
    setHourlyBuckets(null)
    postQueue.current = []
    pendingCompletion.current = null
    setRankingCoverage('Posts will appear as they arrive')
    setBusy('Starting the investigation…')
    setError('')
    try {
      const response = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seed: seedInput, mode }) })
      const data = await response.json() as StartedRun & { error?: string }
      if (!response.ok) throw new Error(data.error || 'Live exploration failed')
      if (id !== requestId.current) return
      streamRunId.current = data.runId
      const stream = new EventSource(data.eventsUrl)
      streamRef.current = stream
      stream.addEventListener('sequitor', (raw) => {
        if (id !== requestId.current) return
        const message = JSON.parse((raw as MessageEvent).data) as StreamEvent
        if (message.sequence <= lastSequence.current) return
        lastSequence.current = message.sequence
        const payload = message.payload
        if (message.type === 'stage') setBusy(String(payload.name || 'Investigating…'))
        if (message.type === 'plan.ready' || message.type === 'context.expanded') setRun(previous => ({ ...previous, searchPlan: payload.plan as Run['searchPlan'] }))
        if (message.type === 'seed.resolved') setRun(previous => ({ ...previous, title: String(payload.text || previous.title).split('\n')[0].slice(0, 110) }))
        if (message.type === 'run.ready') {
          const ready = hydrateRecordedContext(payload as unknown as Run)
          setRun({ ...ready, posts: [], savedPeriods: undefined })
          setSelectedDay(ready.selectedDay)
          setPeriodPosts([])
          postQueue.current = []
          pendingCompletion.current = null
          setRankingCoverage(ready.rankingCoverage || 'Posts arriving…')
          setBusy(ready.streamSource === 'cache' ? 'Loading cached results…' : 'Retrieving posts…')
        }
        if (message.type === 'posts.upsert') {
          const posts = payload.posts as Post[]
          queueStreamPosts(posts, id)
        }
        if (message.type === 'buckets.upsert') {
          const bucket = payload.bucket as Bucket
          setRun(previous => ({ ...previous, buckets: previous.buckets.map(item => item.day === bucket.day ? bucket : item) }))
        }
        if (message.type === 'model.ready') setRun(previous => ({ ...previous, model: { ...previous.model, baseten: payload.model as NonNullable<Run['model']>['baseten'] } }))
        if (message.type === 'run.completed') {
          if (postQueue.current.length || postQueueTimer.current !== null) pendingCompletion.current = payload
          else completeStream(payload)
        }
        if (message.type === 'run.failed' || message.type === 'run.stopped') {
          setBusy('')
          setError(String(payload.message || (message.type === 'run.stopped' ? 'Investigation stopped' : 'Investigation failed')))
          stream.close()
          streamRunId.current = null
        }
      })
      stream.onerror = () => {
        if (id !== requestId.current) return
        // EventSource reconnects and resumes after its Last-Event-ID automatically.
        setBusy(previous => previous || 'Reconnecting to the investigation…')
      }
      setHealth(true)
    } catch (cause) {
      if (id !== requestId.current) return
      setBusy(''); setError(cause instanceof Error ? cause.message : 'Live exploration failed')
    }
  }

  async function chooseDay(day: string) {
    const id = ++requestId.current
    stopCurrent()
    setSelectedDay(day); setError('')
    if (run.kind === 'saved') {
      const periods = run.savedPeriods || (run.id === fallback.id ? fallback.savedPeriods : undefined)
      setPeriodPosts(periods?.[day]?.posts || (run.id === sevenPostFallback.id ? sevenPostFallback.posts : run.posts))
      setRankingCoverage(periods?.[day]?.rankingCoverage || 'No posts saved for this date')
      setBusy(''); return
    }
    setBusy(`Collecting posts for ${formatDay(day)}…`)
    try {
      const data = await getJson<PeriodResult>(`/api/period?run=${encodeURIComponent(run.id)}&day=${encodeURIComponent(day)}`)
      if (id !== requestId.current) return
      setPeriodPosts(data.posts); setRankingCoverage(data.rankingCoverage); setBusy('')
      setRun(previous => ({ ...previous, xSpend: data.xSpend }))
    } catch (cause) {
      if (id !== requestId.current) return
      setPeriodPosts([]); setBusy(''); setError(cause instanceof Error ? cause.message : 'Could not load the selected day')
    }
  }

  const visible = useMemo(() => {
    const dayPosts = periodPosts.filter(post => post.publishedAt?.startsWith(selectedDay))
    // A first X page can contain a reply from just outside the selected UTC
    // day. Keep that evidence visible while the selected-day page is arriving
    // instead of showing an empty feed beneath a live activity chart.
    const arriving = busy && dayPosts.length === 0 ? periodPosts : dayPosts
    return (busy ? arriving : [...dayPosts].sort((a, b) => sort === 'popular'
      ? (b.likes ?? -1) - (a.likes ?? -1) || a.id.localeCompare(b.id)
      : sort === 'recent' ? b.publishedAt.localeCompare(a.publishedAt)
      : (b.rankingScore ?? -1) - (a.rankingScore ?? -1) || (b.likes ?? -1) - (a.likes ?? -1))).slice(0, 10)
  }, [periodPosts, selectedDay, sort, busy])
  const discoveries = useMemo(() => {
    const visibleIds = new Set(visible.map(post => post.id))
    const candidates = periodPosts.filter(post => post.publishedAt?.startsWith(selectedDay) && !visibleIds.has(post.id)
      && post.text.replace(/https?:\/\/\S+/g, '').trim().length >= 35
      && (post.basetenPick || post.scope === 'broader discovery' || post.scope === 'direct conversation' || post.scope === 'humor branch'
        || ['joke', 'criticism', 'question'].includes(post.basetenKind || '')))
      .sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1))
    const humor = candidates.find(post => post.scope === 'humor branch')
    return [...(humor ? [humor] : []), ...candidates.filter(post => post.id !== humor?.id)].slice(0, 3)
  }, [periodPosts, selectedDay, visible])
  const baseten = run.model?.baseten
  const basetenLabel = typeof baseten === 'string' ? baseten : baseten?.status || 'not run'
  const graphPosts = useMemo(() => {
    const candidates = [...periodPosts, ...run.posts]
    if (!busy || run.streamSource !== 'recorded') {
      for (const period of Object.values(run.savedPeriods || {})) candidates.push(...period.posts)
    }
    if (run.seedPost) candidates.push(run.seedPost)
    return [...new Map(candidates.map(post => [post.id, post])).values()]
  }, [periodPosts, run, busy])
  const graphSeedId = run.seedPost?.id || run.seed.match(/\/status\/(\d+)/)?.[1] || graphPosts[0]?.id || ''
  const graphAnnotations = useMemo(() => graphSeedId === storyCapture.seedId
    ? storyCapture.annotations as Record<string, StoryAnnotation>
    : inferredAnnotations(graphPosts), [graphPosts, graphSeedId])
  const activityBuckets = useMemo(() => {
    if (activityScale === 'month') return aggregateMonths(run.buckets)
    if (activityScale === 'hour') return hourlyBuckets || (run.kind === 'saved' ? sampleHourly(periodPosts, selectedDay) : [])
    return run.buckets
  }, [activityScale, hourlyBuckets, periodPosts, run.buckets, run.kind, selectedDay])

  return <div className="seq-shell">
    <a className="seq-skip" href="#seq-main">Skip to posts</a>
    <header className="seq-topbar"><Wordmark /><span className="seq-topbar-right"><span className={`seq-live-dot ${run.kind === 'saved' || run.streamSource === 'cache' ? 'is-saved' : ''}`} />{run.streamSource === 'cache' ? 'Cached X activity' : run.kind === 'saved' ? 'Recorded X activity' : 'Live X activity'}<button onClick={() => setShowData(true)} aria-label="About the data"><Info size={17} /></button></span></header>
    <div className="seq-intro"><div><h1>Follow the conversation.</h1><p>See when a post took off, what people said, and where it went next.</p></div>
      <div className="seq-start-actions">{health === true && <form className="seq-search" onSubmit={explore}><Link2 size={17} aria-hidden="true" /><input aria-label="X post URL or topic" value={seed} onChange={event => setSeed(event.target.value)} placeholder="Paste an X post URL or topic" /><button type="submit"><Search size={16} /><span>Explore live</span></button></form>}
        <button className="seq-recorded-cta" type="button" onClick={replayExample}>Replay the Dario example <ArrowRight size={17} /></button>
        <button className="seq-recorded-cta" type="button" onClick={openWetLabTest}>View Anthropic Wet Lab test <ArrowRight size={17} /></button></div>
    </div>
    {error && <div className="seq-error" role="alert">{error} <button onClick={() => setError('')}>Dismiss</button></div>}
    <div className="seq-investigation-head seq-reveal"><div><span className="seq-investigation-caption">CURRENT CONVERSATION</span><h2>{run.title.split(':')[0]}</h2><p>{run.streamSource === 'cache' ? 'Cached results from an earlier live investigation.' : run.kind === 'saved' ? 'A recorded conversation you can explore offline.' : 'Measured search, with original posts kept in view.'}</p></div><button className="seq-data-button" onClick={() => setShowData(true)}>About this data <ArrowUpRight size={15} /></button></div>
    <nav className="seq-view-tabs" aria-label="Investigation views"><button type="button" className={view === 'feed' ? 'active' : ''} aria-current={view === 'feed' ? 'page' : undefined} onClick={() => setView('feed')}>Activity & posts</button><button type="button" className={view === 'network' ? 'active' : ''} aria-current={view === 'network' ? 'page' : undefined} onClick={() => setView('network')}>Neighborhood <span>{graphPosts.length}</span></button></nav>
    {view === 'feed' ? <main id="seq-main" className="seq-layout">
      <aside className="seq-sidebar"><Timeline buckets={activityBuckets} selectedDay={selectedDay} onSelect={chooseDay} kind={run.streamSource === 'cache' ? 'saved' : run.kind} scaleMax={activityScale === 'day' ? run.activityScaleMax : undefined} contextQuery={run.searchPlan?.volumeFallback} scale={activityScale} onScaleChange={setActivityScale} loading={activityLoading} />
        <ContextCard plan={run.searchPlan} />
        <section className="seq-sidebar-note"><p className="seq-sidebar-note-title">A slice of the discussion</p><p>{run.note}</p><button onClick={() => setShowData(true)}>See scope and sources <ArrowRight size={13} /></button></section>
        {run.model?.openai && <section className="seq-model-trace"><p>{run.kind === 'saved' ? 'RECORDED MODEL RUN' : 'POWERED BY'}</p><span>OpenAI <small>{run.model.openai}</small></span><span>Baseten <small>{basetenLabel}</small></span></section>}
      </aside>
      <section className="seq-feed seq-reveal" aria-label="Posts from selected day"><div className="seq-feed-head"><div><p>Conversation on</p><h2>{formatDay(selectedDay)} <small>UTC</small></h2></div><div className="seq-feed-actions"><button className={sort === 'relevance' ? 'active' : ''} onClick={() => setSort('relevance')}>Sequitor</button><button className={sort === 'popular' ? 'active' : ''} onClick={() => setSort('popular')}>Popular</button><button className={sort === 'recent' ? 'active' : ''} onClick={() => setSort('recent')}>Recent</button></div></div>
        <div className="seq-feed-status"><span>{run.id === sevenPostFallback.id ? 'Selected saved posts' : rankingCoverage}</span><span>{visible.length} shown</span></div>
        {busy && <div className="seq-stream-status" role="status" aria-live="polite"><span className="seq-stream-pulse" /><span>{busy}</span><span className="seq-stream-count">{periodPosts.length ? `${periodPosts.length} retrieved` : 'Waiting for the first results'}</span><button type="button" onClick={() => { ++requestId.current; stopCurrent(); setBusy('') }}>Stop</button></div>}
        {visible.length ? <div className="seq-post-list">{visible.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</div> : busy ? <div className="seq-stream-skeleton" aria-hidden="true"><i /><i /><i /></div> : <div className="seq-empty"><Clock3 size={21} /><h3>No retrieved posts for this day</h3><p>The count can include posts that were not fetched for this feed. Choose another day or try a different seed.</p></div>}
        {!busy && discoveries.length > 0 && <section className="seq-offshoots"><div className="seq-offshoots-heading"><Sparkles size={17} /><div><h3>A different turn</h3><p>Related replies and reactions beyond the ten posts above</p></div></div>{discoveries.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</section>}
        <div className="seq-feed-bottom"><span>{run.id === sevenPostFallback.id ? 'Selected source capture' : `${run.kind === 'saved' ? 'Estimated X spend at capture' : 'Estimated X spend in this server'}: $${(run.xSpend || 0).toFixed(2)}`}</span><span>Likes reflect collection time, not the selected day.</span></div>
      </section>
    </main> : <main id="seq-main"><Neighborhood posts={graphPosts} seedId={graphSeedId}
      referencePosts={graphSeedId === storyCapture.seedId ? recordedReferencePosts : undefined}
      selectedPostIds={graphSeedId === storyCapture.seedId ? storyCapture.selectedPostIds : undefined}
      annotations={graphAnnotations}
      semanticEdges={graphSeedId === storyCapture.seedId ? storyCapture.similarityEdges as SemanticEdge[] : undefined}
      modelLabel={graphSeedId === storyCapture.seedId ? storyCapture.model : undefined}
      onOpenPost={setInspect} /></main>}
    <footer className="seq-footer"><Wordmark /><span>Explore the posts. Keep the limits in view.</span><button onClick={() => setShowData(true)}>Method and sources <ArrowUpRight size={13} /></button></footer>
    {inspect && <Context post={inspect} posts={graphPosts} onClose={() => setInspect(null)} />}
    {showData && <div className="seq-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setShowData(false) }}><aside className="seq-drawer seq-info-drawer" aria-label="About the data"><div className="seq-drawer-head"><button onClick={() => setShowData(false)}><ArrowLeft size={16} /> Back</button><h2>About this view</h2><button className="seq-icon" onClick={() => setShowData(false)} aria-label="Close data details"><X size={18} /></button></div><div className="seq-drawer-content"><h3>What the bars count</h3><p>{run.note}</p><p><strong>Scope:</strong> {run.scope}{run.query ? ` · ${run.query}` : ''}</p><h3>What the feed contains</h3><p>{rankingCoverage}. Posts are sorted by likes recorded at collection time. The feed excludes native retweet copies and can include an explicitly marked related search outside the measured phrase.</p><h3>Models in this run</h3><p><strong>OpenAI:</strong> {run.model?.openai || 'not run'}. It plans bounded literal searches from the seed text.</p><p><strong>Baseten:</strong> {basetenLabel}. It groups or compares retrieved posts; it does not determine truth, copying, or popularity.</p>{run.searchPlan?.discoveryPhrase && <p><strong>Related query:</strong> {run.searchPlan.discoveryPhrase}. {run.searchPlan.whyDiscovery}</p>}<h3>Source fidelity</h3><p>Post text and IDs come from X responses or the saved source snapshot. An earlier post, similar wording, or quote does not by itself prove who influenced whom.</p><p className="seq-data-time"><Check size={14} /> Captured {run.capturedAt ? formatTime(run.capturedAt) : 'at an unknown time'}</p></div></aside></div>}
  </div>
}
