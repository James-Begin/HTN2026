import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowLeft, ArrowRight, ArrowUpRight, BarChart3, Check, Clock3, Heart, Info, Link2, Search, Sparkles, X } from 'lucide-react'
import snapshot from '../../demo/recordings/pace-the-frontier/snapshot.json'
import liveCapture from '../../demo/recordings/sequitor-live.json'
import darioHumorCapture from '../../demo/recordings/dario-humor.json'
import storyCapture from '../../demo/recordings/sequitor-story.json'
import ConversationSpace from './ConversationSpace'
import type { GraphPost } from './graphData'
import './sequitor.css'

type Post = {
  id: string; text: string; publishedAt: string; author: string; handle?: string
  avatar?: string; likes?: number | null; reposts?: number | null; replies?: number | null
  url?: string; parentId?: string | null; quotedPostId?: string | null
  scope?: string; captureTime?: string; textIsExcerpt?: boolean; sourceType?: 'input'
  basetenKind?: string; sameClaimScore?: number; sameClaimRegister?: string; rerankerScore?: number; rerankerModel?: string
  basetenPick?: boolean; semanticScore?: number; lexicalScore?: number
  rankingScore?: number; rankingMethod?: string
  spaceScore?: number; spaceY?: number; spaceZ?: number; spaceDirectionQuality?: number; spaceMethod?: string
}
type Bucket = { day: string; count: number | null; coverage: 'complete' | 'partial' | 'sample' | 'unavailable'; pending?: boolean }
type RunStatus = 'running' | 'reconnecting' | 'completed' | 'stopped' | 'failed'
type HourlyState = { key: string; buckets: Bucket[] | null; loading: boolean; error?: string }
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
      merged.push(normalizePost(post))
    } else {
      const prior = merged[index]
      merged[index] = normalizePost({ ...prior, ...post,
        textIsExcerpt: prior.text === post.text && prior.textIsExcerpt ? true : post.textIsExcerpt })
    }
  }
  return merged
}

const defaultSeed = 'https://x.com/DarioAmodei/status/2098773920774074715'
// The source snapshot retains the original profile payload separately from the
// selected post list. Keep that captured avatar with its matching source post.
const recordedAvatars: Record<string, string> = {
  '2098773920774074715': 'https://pbs.twimg.com/profile_images/2015835742577012736/uOwdzrEz_normal.jpg',
}
const sourcePosts: Post[] = snapshot.posts.map(post => ({
  id: post.id, text: post.text, publishedAt: post.publishedAt, author: post.author,
  handle: post.handle, likes: post.likes, url: post.url,
  avatar: recordedAvatars[post.id],
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
function isInput(post: Post) {
  return post.sourceType === 'input' || post.id === 'seed-text' || post.author === 'Seed text'
}
function normalizePost(post: Post): Post {
  if (isInput(post)) return { ...post, sourceType: 'input', author: 'Search input', publishedAt: '', url: undefined }
  const knownExcerpt = sourcePosts.some(source => source.id === post.id && source.text === post.text && source.textIsExcerpt)
  const normalized = knownExcerpt ? { ...post, textIsExcerpt: true } : post
  const avatar = normalized.avatar || recordedAvatars[normalized.id]
  return avatar ? { ...normalized, avatar } : normalized
}
function hydrateRecordedContext(run: Run): Run {
  // Repair display metadata, never source text, capture hashes, or the query
  // that actually produced the historical counts. A later plan is not a measurement.
  return { ...run,
    buckets: run.buckets.map(bucket => normalizeBucket(bucket, run.capturedAt)),
    posts: run.posts.map(normalizePost),
    seedPost: run.seedPost ? normalizePost(run.seedPost) : undefined,
    savedPeriods: run.savedPeriods ? Object.fromEntries(Object.entries(run.savedPeriods).map(([day, period]) =>
      [day, { ...period, posts: period.posts.map(normalizePost) }])) : undefined,
  }
}
const fallback: Run = {
  ...withDarioHumor(hydrateRecordedContext(liveCapture as Run)), kind: 'saved',
  scope: 'Recorded X counts and retrieved posts',
  note: `Saved run captured ${formatTime(liveCapture.capturedAt)}. Its bars were measured on X at capture time; post lists cover retrieved candidates only. Three humor-search posts were added later with separate capture timestamps.`,
}
const recordedReferencePosts: GraphPost[] = [...new Map([
  ...fallback.posts,
  ...Object.values(fallback.savedPeriods || {}).flatMap(period => period.posts),
  ...(fallback.seedPost ? [fallback.seedPost] : []),
].map(post => [post.id, post])).values()]

function pendingActivity(run: Run): Run {
  return { ...run, activityScaleMax: Math.max(1, ...run.buckets.map(bucket => bucket.count ?? 0)),
    buckets: run.buckets.map(bucket => ({ ...bucket, count: 0, pending: true })) }
}

function formatDay(day: string, withYear = true) {
  if (!day || Number.isNaN(Date.parse(`${day}T12:00:00Z`))) return 'Date not selected'
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
function normalizeBucket(bucket: Bucket, capturedAt?: string): Bucket {
  if (bucket.coverage === 'unavailable') return { ...bucket, count: null }
  // A daily count captured during that same UTC day cannot cover the full day.
  return bucket.coverage === 'complete' && capturedAt?.slice(0, 10) === bucket.day
    ? { ...bucket, coverage: 'partial' } : bucket
}
function aggregateMonths(buckets: Bucket[]): Bucket[] {
  const months = new Map<string, Bucket[]>()
  for (const bucket of new Map(buckets.map(item => [item.day, item])).values()) {
    const month = bucket.day.slice(0, 7)
    months.set(month, [...(months.get(month) || []), bucket])
  }
  return [...months.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, days]) => {
    const calendarDays = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).getUTCDate()
    const sample = days.every(day => day.coverage === 'sample')
    const mixed = !sample && days.some(day => day.coverage === 'sample')
    const unknown = mixed || days.some(day => day.count === null || day.coverage === 'unavailable')
    return { day: `${month}-01`, count: unknown ? null : days.reduce((sum, day) => sum + (day.count ?? 0), 0),
      coverage: unknown ? 'unavailable' : sample ? 'sample' : days.length === calendarDays && days.every(day => day.coverage === 'complete') ? 'complete' : 'partial',
      pending: days.some(day => day.pending) }
  })
}
function sampleHourly(posts: Post[], selectedDay: string): Bucket[] {
  if (!selectedDay) return []
  // Zeros here mean no captured candidates in that hour, never no X activity.
  return Array.from({ length: 24 }, (_, hour) => {
    const start = `${selectedDay}T${String(hour).padStart(2, '0')}`
    return { day: `${start}:00:00Z`, count: posts.filter(post => !isInput(post) && post.publishedAt.startsWith(start)).length, coverage: 'sample' }
  })
}
function activityLabel(value: string, scale: ActivityScale) {
  if (scale === 'hour') return new Intl.DateTimeFormat('en-CA', { hour: 'numeric', timeZone: 'UTC' }).format(new Date(value)) + ' UTC'
  if (scale === 'month') return new Intl.DateTimeFormat('en-CA', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value))
  return formatDay(value)
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function validPost(value: unknown): value is Post {
  return record(value) && ['id', 'text', 'publishedAt', 'author'].every(key => typeof value[key] === 'string')
    && ['handle', 'avatar', 'url', 'scope', 'captureTime', 'basetenKind', 'rankingMethod', 'spaceMethod', 'parentId', 'quotedPostId'].every(key => value[key] == null || typeof value[key] === 'string')
    && ['likes', 'reposts', 'replies', 'rankingScore', 'sameClaimScore', 'semanticScore', 'lexicalScore', 'spaceScore', 'spaceY', 'spaceZ', 'spaceDirectionQuality'].every(key => value[key] == null || typeof value[key] === 'number' && Number.isFinite(value[key]))
}
function validBucket(value: unknown): value is Bucket {
  return record(value) && typeof value.day === 'string' && !Number.isNaN(Date.parse(value.day))
    && (value.count === null || typeof value.count === 'number' && Number.isFinite(value.count) && value.count >= 0)
    && ['complete', 'partial', 'sample', 'unavailable'].includes(String(value.coverage))
}
function validPlan(value: unknown) {
  return value === null || record(value)
    && ['contextLabel', 'volumePhrase', 'volumeFallback', 'discoveryPhrase', 'expansionReason', 'whyDiscovery', 'model', 'error'].every(key => value[key] == null || typeof value[key] === 'string')
    && ['entities', 'angles', 'uncertainties', 'discoveryQueries', 'expansionQueries'].every(key => value[key] == null || Array.isArray(value[key]) && value[key].every(item => typeof item === 'string'))
}
function validCuration(value: unknown): boolean {
  return value == null || typeof value === 'string' || record(value)
    && ['status', 'model'].every(key => value[key] == null || typeof value[key] === 'string')
}
function validModel(value: unknown): boolean {
  return value == null || record(value) && (value.openai == null || typeof value.openai === 'string') && validCuration(value.baseten)
}
function validateEvent(message: StreamEvent) {
  const payload = message.payload
  let valid = true
  if (message.type === 'run.ready') valid = ['id', 'seed', 'title', 'scope', 'selectedDay', 'rankingCoverage', 'note'].every(key => typeof payload[key] === 'string')
    && ['live', 'saved'].includes(String(payload.kind)) && Array.isArray(payload.posts) && payload.posts.every(validPost)
    && Array.isArray(payload.buckets) && payload.buckets.every(validBucket) && (payload.seedPost == null || validPost(payload.seedPost))
    && (payload.searchPlan == null || validPlan(payload.searchPlan)) && validModel(payload.model)
  if (message.type === 'model.ready') valid = validCuration(payload.model)
  if (message.type === 'run.completed') valid = validModel(payload.model)
  if (payload.xSpend != null) valid = valid && typeof payload.xSpend === 'number' && Number.isFinite(payload.xSpend)
  if (message.type === 'posts.upsert') valid = Array.isArray(payload.posts) && payload.posts.every(validPost)
  if (message.type === 'buckets.upsert') valid = validBucket(payload.bucket)
  if (message.type === 'seed.resolved') valid = typeof payload.text === 'string' && (payload.post == null || validPost(payload.post))
  if (message.type === 'plan.ready' || message.type === 'context.expanded') valid = validPlan(payload.plan)
  if (!valid) throw new Error('Invalid investigation event received; partial results retained')
}
async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || 'Could not load the data')
  return data as T
}

function Wordmark() {
  return <span className="seq-wordmark"><span className="seq-mark" aria-hidden="true"><i /><i /><i /></span>sequitor<span className="seq-wordmark-dot">.</span></span>
}

function Timeline({ buckets, selectedDay, onSelect, kind, scaleMax, query, scale, onScaleChange, loading, error, sample }: { buckets: Bucket[]; selectedDay: string; onSelect: (day: string) => void; kind: Run['kind']; scaleMax?: number; query?: string | null; scale: ActivityScale; onScaleChange: (scale: ActivityScale) => void; loading?: boolean; error?: string; sample?: boolean }) {
  const max = Math.max(1, scaleMax || 0, ...buckets.map(bucket => bucket.count ?? 0))
  const selected = scale === 'day' ? buckets.find(bucket => bucket.day === selectedDay) : undefined
  const displayed = scale === 'day' ? selected ? [selected] : [] : buckets
  const unavailable = !displayed.length || displayed.some(bucket => bucket.count === null || bucket.coverage === 'unavailable')
  const pending = displayed.some(bucket => bucket.pending)
  const total = unavailable ? null : displayed.reduce((sum, bucket) => sum + (bucket.count ?? 0), 0)
  const isSample = sample || buckets.some(bucket => bucket.coverage === 'sample')
  const partial = displayed.some(bucket => bucket.coverage === 'partial')
  const bucketLabel = (bucket: Bucket) => `${activityLabel(bucket.day, scale)}: ${bucket.pending ? 'awaiting count' : bucket.count === null ? 'count unavailable' : `${bucket.count.toLocaleString()} ${bucket.coverage === 'sample' ? 'saved' : 'matching'} posts${bucket.coverage === 'partial' ? ' · partial coverage' : ''}`}`
  return <section className="seq-timeline" aria-label="Activity over time">
    <div className="seq-section-top"><div><h2>Activity over time</h2><p>{isSample ? 'Selected saved posts' : query ? `X posts matching ${query}` : 'Measured query not available'}</p></div><BarChart3 size={18} aria-hidden="true" /></div>
    <div className="seq-activity-scale" role="group" aria-label="Activity resolution">{(['day', 'hour', 'month'] as const).map(value => <button key={value} type="button" className={scale === value ? 'active' : ''} aria-pressed={scale === value} onClick={() => onScaleChange(value)}>{value === 'day' ? 'Daily' : value === 'hour' ? 'Hourly' : 'Monthly'}</button>)}</div>
    <div className="seq-activity-total"><strong>{loading || pending || error ? '—' : shortNumber(total)}</strong><span>{scale === 'hour' ? `posts across ${formatDay(selectedDay)} by hour` : scale === 'month' ? 'posts in the captured months' : <>posts on {formatDay(selectedDay)} <span className="seq-utc">UTC</span></>}</span></div>
    <div className="seq-chart" role="group" aria-label={scale === 'day' ? 'Choose a day' : `${scale} activity`}>
      {buckets.map(bucket => <button key={bucket.day} type="button" className={`seq-bar ${scale === 'day' && bucket.day === selectedDay ? 'is-selected' : ''} ${bucket.coverage !== 'complete' ? 'is-partial' : ''} ${bucket.pending ? 'is-pending' : ''}`}
        style={{ height: '100%', transform: `scaleY(${bucket.pending || bucket.count === null ? 0 : Math.max(.09, Math.sqrt(bucket.count / max))})` }}
        title={bucketLabel(bucket)} aria-label={bucketLabel(bucket)}
        aria-pressed={scale === 'day' && bucket.day === selectedDay} disabled={bucket.pending || bucket.count === null || scale !== 'day'} onClick={() => onSelect(bucket.day)}><span className="sr-only">{activityLabel(bucket.day, scale)}</span></button>)}
    </div>
    <div className="seq-chart-axis"><span>{buckets.length ? activityLabel(buckets[0].day, scale) : ''}</span><span>{buckets.length ? activityLabel(buckets[buckets.length - 1].day, scale) : ''}</span></div>
    <p className="seq-timeline-foot">{error ? `${error} · ` : unavailable && !loading ? 'Count unavailable · ' : ''}{isSample ? 'Sample counts · not platform activity' : query ? `One measured query · retweets included · ${kind === 'saved' ? 'saved measurement' : 'live measurement'}` : 'No measurement received'}{scale === 'hour' ? isSample ? ' · saved post timestamps by hour' : ' · hourly count request for selected day' : scale === 'month' ? ' · monthly roll-up of captured days' : ''}{partial ? ' · partial coverage' : ''}</p>
  </section>
}

function ContextCard({ plan }: { plan?: Run['searchPlan'] }) {
  if (!plan?.contextLabel) return null
  const queries = [...(plan.discoveryQueries || []), ...(plan.expansionQueries || [])]
  return <section className="seq-context-card" aria-label="Investigation context">
    <p>OPENAI CONTEXT CARD</p><h3>{plan.contextLabel}</h3>
    {plan.entities?.length ? <div><span>Entities</span><p>{plan.entities.join(' · ')}</p></div> : null}
    {plan.volumeFallback && <div><span>Planned context query</span><p><code>{plan.volumeFallback}</code></p></div>}
    {queries.length ? <div><span>Discovery branches</span><p>{queries.map(query => <code key={query}>{query}</code>)}</p></div> : null}
    {plan.expansionReason && <small>Second pass: {plan.expansionReason}</small>}
    {plan.uncertainties?.[0] && <small>Limit: {plan.uncertainties[0]}</small>}
  </section>
}

function PostRow({ post, onOpen }: { post: Post; onOpen: (post: Post) => void }) {
  if (isInput(post)) return <section className="seq-context-empty" aria-label="Search input"><strong>Search input · not an X post</strong><p className="seq-post-text">{post.text}</p></section>
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

function Drawer({ title, label = title, closeLabel, onClose, children }: { title: string; label?: string; closeLabel: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const backdropDown = useRef(false)
  useLayoutEffect(() => {
    const dialog = ref.current!
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    dialog.showModal()
    document.body.style.overflow = 'hidden'
    return () => {
      dialog.close()
      document.body.style.overflow = overflow
      if (trigger?.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [])
  return <dialog ref={ref} className="seq-overlay" aria-label={label} aria-modal="true"
    onCancel={event => { event.preventDefault(); onClose() }}
    onPointerDown={event => { backdropDown.current = event.target === event.currentTarget }}
    onClick={event => { if (backdropDown.current && event.target === event.currentTarget) onClose() }}>
    <div className="seq-drawer"><div className="seq-drawer-head"><button onClick={onClose}><ArrowLeft size={16} /> Back</button><h2>{title}</h2><button className="seq-icon" onClick={onClose} aria-label={closeLabel}><X size={18} /></button></div>{children}</div>
  </dialog>
}

function Context({ post, posts, onClose }: { post: Post; posts: Post[]; onClose: () => void }) {
  const relationId = post.quotedPostId || post.parentId
  const local = posts.find(item => item.id === relationId)
  const [fetched, setFetched] = useState<Post | null>(null)
  const related = local || (fetched?.id === relationId ? fetched : null)
  useEffect(() => {
    const controller = new AbortController()
    if (relationId && !local) {
      getJson<Post>(`/api/context?id=${encodeURIComponent(relationId)}`, controller.signal)
        .then(result => { if (!controller.signal.aborted && result.id === relationId) setFetched(normalizePost(result)) }).catch(() => {})
    }
    return () => controller.abort()
  }, [relationId, local])
  return <Drawer title="Post context" closeLabel="Close context" onClose={onClose}>
      <div className="seq-drawer-content"><p className="seq-drawer-label">SELECTED POST</p><PostRow post={post} onOpen={() => {}} />
        {!isInput(post) && <TweetEmbed post={post} />}
        {relationId && <section className="seq-relationship"><div className="seq-relationship-line" /><p className="seq-drawer-label">{post.quotedPostId ? 'QUOTES' : 'REPLIES TO'}</p>
          {related ? <PostRow post={related} onOpen={() => {}} /> : <a href={`https://x.com/i/status/${relationId}`} target="_blank" rel="noopener noreferrer">Open referenced post on X <ArrowUpRight size={15} /></a>}</section>}
        {!relationId && <p className="seq-context-empty">No quote or reply relationship is recorded for this post. A shared topic does not establish who saw or copied whom.</p>}
        {post.basetenKind && <p className="seq-context-model">Baseten grouped this as “{post.basetenKind}.” This is a model suggestion, not a statement of fact.</p>}
        {post.url && <a className="seq-source-link" href={post.url} target="_blank" rel="noopener noreferrer">View original post on X <ArrowUpRight size={15} /></a>}
      </div>
  </Drawer>
}

export default function Sequitor() {
  const [run, setRun] = useState<Run>(fallback)
  const [seed, setSeed] = useState('')
  const [selectedDay, setSelectedDay] = useState(fallback.selectedDay)
  const [periodPosts, setPeriodPosts] = useState<Post[]>(fallback.posts)
  const [rankingCoverage, setRankingCoverage] = useState(fallback.rankingCoverage)
  const [sort, setSort] = useState<'relevance' | 'popular' | 'recent'>('popular')
  const [busy, setBusy] = useState('')
  const [runStatus, setRunStatus] = useState<RunStatus>('completed')
  const [periodLoading, setPeriodLoading] = useState(false)
  const [error, setError] = useState('')
  const [inspect, setInspect] = useState<Post | null>(null)
  const [showData, setShowData] = useState(false)
  const [view, setView] = useState<'feed' | 'space'>('feed')
  const [health, setHealth] = useState<boolean | null>(null)
  const [activityScale, setActivityScale] = useState<ActivityScale>('day')
  const [hourlyActivity, setHourlyActivity] = useState<HourlyState | null>(null)
  const requestId = useRef(0)
  const periodRequestId = useRef(0)
  const periodController = useRef<AbortController | null>(null)
  const activityController = useRef<AbortController | null>(null)
  const hourlyKey = `${run.id}:${selectedDay}`
  const hourlyEnabled = activityScale === 'hour' && run.kind !== 'saved' && !run.id.startsWith('pending-') && !!selectedDay
  const currentHourly = hourlyActivity?.key === hourlyKey ? hourlyActivity : null
  const hourlyBuckets = currentHourly?.buckets ?? null
  const activityLoading = hourlyEnabled && (!currentHourly || currentHourly.loading)
  const activityError = hourlyEnabled ? currentHourly?.error : undefined
  const streamRef = useRef<EventSource | null>(null)
  const streamRunId = useRef<string | null>(null)
  const replayTimer = useRef<number | null>(null)
  const postQueue = useRef<Post[]>([])
  const postQueueTimer = useRef<number | null>(null)
  const pendingCompletion = useRef<Record<string, unknown> | null>(null)
  const lastSequence = useRef(0)

  useEffect(() => () => {
    ++requestId.current
    ++periodRequestId.current
    stopCurrent()
  }, [])

  useEffect(() => {
    if (!hourlyEnabled) return
    const controller = new AbortController()
    activityController.current = controller
    setHourlyActivity({ key: hourlyKey, buckets: null, loading: true })
    getJson<ActivityResult>(`/api/activity?run=${encodeURIComponent(run.id)}&day=${encodeURIComponent(selectedDay)}&granularity=hour`, controller.signal)
      .then(result => {
        if (controller.signal.aborted) return
        if (result.granularity !== 'hour' || result.day !== selectedDay || result.query !== run.query || !Array.isArray(result.buckets) || !result.buckets.every(validBucket)) throw new Error('Hourly measurement did not match the requested period and query')
        setHourlyActivity({ key: hourlyKey, buckets: result.buckets.map(bucket => normalizeBucket(bucket)), loading: false })
        setRun(previous => previous.id === run.id ? { ...previous, xSpend: result.xSpend } : previous)
      })
      .catch(cause => {
        if (!controller.signal.aborted) setHourlyActivity({ key: hourlyKey, buckets: null, loading: false,
          error: cause instanceof Error ? cause.message : 'Could not measure hourly activity' })
      })
    return () => controller.abort()
  }, [hourlyEnabled, hourlyKey, run.id, run.query, selectedDay])

  useEffect(() => {
    const controller = new AbortController()
    const id = requestId.current
    getJson<Run>('/api/demo', controller.signal).then(demo => {
      if (controller.signal.aborted) return
      const recorded = hydrateRecordedContext(demo)
      if (id === requestId.current) { setRun(recorded); setSelectedDay(recorded.selectedDay); setPeriodPosts(recorded.posts); setRankingCoverage(recorded.rankingCoverage) }
      setHealth(true)
    }).catch(() => { if (!controller.signal.aborted) setHealth(false) })
    return () => controller.abort()
  }, [])

  function cancelJob(id: string) {
    fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }).catch(() => {})
  }

  function flushPosts() {
    if (postQueueTimer.current !== null) window.clearTimeout(postQueueTimer.current)
    postQueueTimer.current = null
    const received = postQueue.current.splice(0)
    if (received.length) {
      setPeriodPosts(previous => mergePosts(previous, received))
      setRun(previous => ({ ...previous, posts: mergePosts(previous.posts, received) }))
    }
    pendingCompletion.current = null
  }

  function stopCurrent() {
    streamRef.current?.close()
    streamRef.current = null
    periodController.current?.abort()
    activityController.current?.abort()
    if (replayTimer.current !== null) window.clearInterval(replayTimer.current)
    replayTimer.current = null
    if (postQueueTimer.current !== null) window.clearTimeout(postQueueTimer.current)
    postQueueTimer.current = null
    postQueue.current = []
    pendingCompletion.current = null
    if (streamRunId.current) {
      cancelJob(streamRunId.current)
      streamRunId.current = null
    }
  }

  function resetRequests() {
    stopCurrent()
    ++periodRequestId.current
    setPeriodLoading(false)
    setHourlyActivity(null)
    setActivityScale('day')
    setInspect(null)
    setShowData(false)
    setSort('popular')
  }

  function stopInvestigation() {
    ++requestId.current
    ++periodRequestId.current
    flushPosts()
    stopCurrent()
    setPeriodLoading(false)
    setHourlyActivity(previous => previous?.loading ? { ...previous, loading: false, error: 'Measurement stopped' } : previous)
    setBusy('')
    setRunStatus('stopped')
    setRankingCoverage('Stopped · partial retrieved results retained')
  }

  function completeStream(payload: Record<string, unknown>) {
    setRun(previous => ({ ...previous, model: payload.model as Run['model'] || previous.model,
      xSpend: typeof payload.xSpend === 'number' ? payload.xSpend : previous.xSpend,
      ...(previous.streamSource === 'recorded' && previous.id === fallback.id
        ? { posts: fallback.posts, savedPeriods: fallback.savedPeriods, buckets: fallback.buckets } : {}) }))
    setRankingCoverage(String(payload.rankingCoverage || 'Retrieved posts'))
    setBusy('')
    setRunStatus('completed')
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
    setRun(previous => ({ ...previous, posts: mergePosts(previous.posts, next) }))
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
    resetRequests()
    setRunStatus('running')
    const recorded = { ...pendingActivity(fallback), posts: [], savedPeriods: undefined, streamSource: 'recorded' as const }
    setRun(recorded)
    setSelectedDay(recorded.selectedDay)
    setPeriodPosts([])
    setSeed(defaultSeed)
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
        setRunStatus('completed')
      }
    }, 170)
  }

  async function explore(event?: FormEvent) {
    event?.preventDefault()
    await startStreaming(seed.trim() || defaultSeed, 'live')
  }

  async function startStreaming(seedInput: string, mode: 'live' | 'recorded') {
    const id = ++requestId.current
    resetRequests()
    lastSequence.current = 0
    setRun({ id: `pending-${id}`, seed: seedInput,
      title: mode === 'recorded' ? fallback.title : seedInput || 'Starting investigation',
      kind: mode === 'recorded' ? 'saved' : 'live', buckets: [], posts: [],
      selectedDay: '', scope: 'Not measured yet', query: null, streamSource: mode,
      note: 'The measured scope and retrieved posts will appear as they arrive.',
      rankingCoverage: 'Posts will appear as they arrive' })
    setSeed(seedInput)
    setSelectedDay('')
    setPeriodPosts([])
    setRunStatus('running')
    setRankingCoverage('Posts will appear as they arrive')
    setBusy('Starting the investigation…')
    setError('')
    try {
      const response = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seed: seedInput, mode }) })
      const data = await response.json() as StartedRun & { error?: string }
      if (!response.ok) throw new Error(data.error || 'Live exploration failed')
      if (typeof data.runId !== 'string' || typeof data.eventsUrl !== 'string') throw new Error('Invalid investigation response')
      // Do not abort creation and lose the job ID: a late response must still
      // cancel the server job when Stop or another search has superseded it.
      if (id !== requestId.current) { cancelJob(data.runId); return }
      streamRunId.current = data.runId
      const stream = new EventSource(data.eventsUrl)
      let terminal = false
      streamRef.current = stream
      stream.addEventListener('sequitor', (raw) => {
        if (id !== requestId.current || terminal) return
        try {
        const decoded: unknown = JSON.parse((raw as MessageEvent).data)
        if (!record(decoded)) throw new Error('Invalid investigation event')
        if (typeof decoded.runId === 'string' && decoded.runId !== data.runId) return
        if (decoded.runId !== data.runId || !Number.isInteger(decoded.sequence) || Number(decoded.sequence) < 1 || typeof decoded.type !== 'string' || !record(decoded.payload)) throw new Error('Invalid investigation event')
        const message = decoded as unknown as StreamEvent
        if (message.sequence <= lastSequence.current) return
        validateEvent(message)
        lastSequence.current = message.sequence
        setRunStatus('running')
        const payload = message.payload
        if (message.type === 'stage') setBusy(String(payload.name || 'Investigating…'))
        if (message.type === 'plan.ready' || message.type === 'context.expanded') setRun(previous => ({ ...previous, searchPlan: payload.plan as Run['searchPlan'] }))
        if (message.type === 'seed.resolved') setRun(previous => ({ ...previous,
          title: String(payload.text || previous.title).split('\n')[0].slice(0, 110),
          seedPost: payload.post ? normalizePost(payload.post as Post) : { id: 'seed-text', sourceType: 'input', author: 'Search input', publishedAt: '', text: String(payload.text) } }))
        if (message.type === 'run.ready') {
          const ready = hydrateRecordedContext(payload as unknown as Run)
          setRun({ ...ready, posts: [], savedPeriods: undefined })
          setSelectedDay(ready.selectedDay)
          setPeriodPosts([])
          if (postQueueTimer.current !== null) window.clearTimeout(postQueueTimer.current)
          postQueueTimer.current = null
          postQueue.current = []
          pendingCompletion.current = null
          setRankingCoverage(ready.rankingCoverage || 'Posts arriving…')
          setBusy(ready.streamSource === 'cache' ? 'Loading cached results…' : 'Retrieving posts…')
        }
        if (message.type === 'posts.upsert') {
          const posts = payload.posts as Post[]
          queueStreamPosts(posts.map(normalizePost), id)
        }
        if (message.type === 'buckets.upsert') {
          const bucket = payload.bucket as Bucket
          setRun(previous => ({ ...previous, buckets: [...new Map([...previous.buckets, normalizeBucket(bucket, previous.capturedAt)].map(item => [item.day, item])).values()].sort((a, b) => a.day.localeCompare(b.day)) }))
        }
        if (message.type === 'model.ready') setRun(previous => ({ ...previous, model: { ...previous.model, baseten: payload.model as NonNullable<Run['model']>['baseten'] } }))
        if (message.type === 'run.completed') {
          terminal = true
          stream.close()
          streamRef.current = null
          streamRunId.current = null
          if (postQueue.current.length || postQueueTimer.current !== null) {
            pendingCompletion.current = payload
            setBusy('Showing received posts…')
          } else completeStream(payload)
        }
        if (message.type === 'run.failed' || message.type === 'run.stopped') {
          terminal = true
          flushPosts()
          setBusy('')
          setRunStatus(message.type === 'run.stopped' ? 'stopped' : 'failed')
          setRankingCoverage('Partial retrieved results retained')
          if (message.type === 'run.failed') setError(String(payload.message || 'Investigation failed'))
          stream.close()
          streamRef.current = null
          streamRunId.current = null
        }
        } catch (cause) {
          terminal = true
          flushPosts()
          stopCurrent()
          setBusy('')
          setRunStatus('failed')
          setRankingCoverage('Invalid stream · partial retrieved results retained')
          setError(cause instanceof Error ? cause.message : 'Invalid investigation event')
        }
      })
      stream.onerror = () => {
        if (id !== requestId.current || terminal) return
        // EventSource reconnects with Last-Event-ID; a closed stream cannot resume.
        if (stream.readyState === EventSource.CLOSED) {
          terminal = true
          flushPosts()
          stopCurrent()
          setBusy('')
          setRunStatus('failed')
          setError('Investigation stream closed; partial results retained')
          setRankingCoverage('Partial retrieved results retained')
        } else {
          setRunStatus('reconnecting')
          setBusy('Reconnecting to the investigation…')
        }
      }
      setHealth(true)
    } catch (cause) {
      if (id !== requestId.current) return
      stopCurrent()
      setRunStatus('failed')
      setRankingCoverage('Investigation failed · no complete results')
      setBusy(''); setError(cause instanceof Error ? cause.message : 'Live exploration failed')
    }
  }

  async function chooseDay(day: string) {
    const id = ++periodRequestId.current
    const runId = ++requestId.current
    flushPosts()
    stopCurrent()
    setBusy('')
    if (runStatus === 'running' || runStatus === 'reconnecting') setRunStatus('stopped')
    setSelectedDay(day); setInspect(null); setError(''); setPeriodLoading(false)
    const periods = run.savedPeriods || (run.kind === 'saved' && run.id === fallback.id ? fallback.savedPeriods : undefined)
    if (run.kind === 'saved' || periods?.[day]) {
      const posts = periods?.[day]?.posts || run.posts.filter(post => post.publishedAt.startsWith(day))
      setPeriodPosts(posts)
      setRankingCoverage(periods?.[day]?.rankingCoverage || (posts.length ? 'Selected saved posts only' : 'No posts saved for this date'))
      return
    }
    const controller = new AbortController()
    periodController.current = controller
    setPeriodPosts([])
    setRankingCoverage('Collecting candidates for this date…')
    setPeriodLoading(true)
    try {
      const data = await getJson<PeriodResult>(`/api/period?run=${encodeURIComponent(run.id)}&day=${encodeURIComponent(day)}`, controller.signal)
      if (id !== periodRequestId.current || runId !== requestId.current || controller.signal.aborted) return
      if (data.day !== day || !Array.isArray(data.posts) || !data.posts.every(validPost)) throw new Error('Period response did not match the selected date')
      const result = { ...data, posts: data.posts.map(normalizePost) }
      setPeriodPosts(result.posts); setRankingCoverage(result.rankingCoverage)
      setRun(previous => ({ ...previous, xSpend: result.xSpend, savedPeriods: { ...previous.savedPeriods, [day]: result } }))
    } catch (cause) {
      if (id !== periodRequestId.current || runId !== requestId.current || controller.signal.aborted) return
      setRankingCoverage('Posts unavailable for this date')
      setError(cause instanceof Error ? cause.message : 'Could not load the selected day')
    } finally {
      if (id === periodRequestId.current && runId === requestId.current) setPeriodLoading(false)
    }
  }

  const visible = useMemo(() => {
    const dayPosts = periodPosts.filter(post => !isInput(post) && selectedDay && post.publishedAt?.startsWith(selectedDay))
    return dayPosts.sort((a, b) => (sort === 'popular'
      ? (b.likes ?? -1) - (a.likes ?? -1)
      : sort === 'recent' ? b.publishedAt.localeCompare(a.publishedAt)
      : (b.rankingScore ?? -1) - (a.rankingScore ?? -1) || (b.likes ?? -1) - (a.likes ?? -1)) || a.id.localeCompare(b.id)).slice(0, 10)
  }, [periodPosts, selectedDay, sort])
  const discoveries = useMemo(() => {
    const visibleIds = new Set(visible.map(post => post.id))
    const candidates = periodPosts.filter(post => !isInput(post) && selectedDay && post.publishedAt?.startsWith(selectedDay) && !visibleIds.has(post.id)
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
    return [...new Map(candidates.filter(post => !isInput(post)).map(post => [post.id, normalizePost(post)])).values()]
  }, [periodPosts, run, busy])
  const graphSeedId = run.seedPost && !isInput(run.seedPost) ? run.seedPost.id : run.seed.match(/\/status\/(\d+)/)?.[1] || ''
  const activityBuckets = useMemo(() => {
    if (activityScale === 'month') return aggregateMonths(run.buckets)
    if (activityScale === 'hour') return hourlyBuckets || (run.kind === 'saved' ? sampleHourly(periodPosts, selectedDay) : [])
    return run.buckets
  }, [activityScale, hourlyBuckets, periodPosts, run.buckets, run.kind, selectedDay])

  const busyLabel = periodLoading ? `Collecting posts for ${formatDay(selectedDay)}…` : busy
  const feedCoverage = busyLabel && periodPosts.length
    ? `${periodPosts.length} retrieved · ranking in progress`
    : rankingCoverage
  const shownLabel = busyLabel ? `${visible.length} shown so far` : `${visible.length} shown`
  const rankDescription = sort === 'popular' ? 'Posts are sorted by likes recorded at collection time.'
    : sort === 'recent' ? 'Posts are sorted by publication time, newest first.'
    : 'Posts are sorted by the supplied retrieval match score, with captured likes breaking ties. A match score is not a truth or influence judgment.'

  return <div className="seq-shell">
    <a className="seq-skip" href="#seq-main">Skip to posts</a>
    <header className="seq-topbar"><Wordmark /><span className="seq-topbar-right"><span className={`seq-live-dot ${run.kind === 'saved' || run.streamSource === 'cache' ? 'is-saved' : ''}`} />{run.streamSource === 'cache' ? 'Cached X activity' : run.kind === 'saved' ? 'Recorded X activity' : 'Live X activity'}<button onClick={() => setShowData(true)} aria-label="About the data"><Info size={17} /></button></span></header>
    <div className="seq-intro" role="region" aria-label="Explore a conversation"><div><h1>Follow the conversation.</h1><p>See when a post took off, what people said, and where it went next.</p></div>
      <div className="seq-start-actions">{health === true && <form className="seq-search" onSubmit={explore}><Link2 size={17} aria-hidden="true" /><input aria-label="X post URL or topic" value={seed} onChange={event => setSeed(event.target.value)} placeholder="Paste an X post URL or topic" /><button type="submit"><Search size={16} /><span>Explore live</span></button></form>}
        <button className="seq-recorded-cta" type="button" onClick={replayExample}>Replay the Dario example <ArrowRight size={17} /></button></div>
    </div>
    {error && <div className="seq-error" role="alert">{error} <button onClick={() => setError('')}>Dismiss</button></div>}
    <div className="seq-investigation-head" role="region" aria-label="Current conversation"><div><span className="seq-investigation-caption">CURRENT CONVERSATION</span><h2>{run.title}</h2><p>{run.seedPost && isInput(run.seedPost) ? 'Search input · no authored starting post supplied.' : run.streamSource === 'cache' ? 'Cached results from an earlier live investigation.' : run.kind === 'saved' ? 'A recorded conversation you can explore offline.' : run.query ? 'Measured search, with original posts kept in view.' : 'No measurement received yet.'}</p></div><button className="seq-data-button" onClick={() => setShowData(true)}>About this data <ArrowUpRight size={15} /></button></div>
    <nav className="seq-view-tabs" aria-label="Investigation views"><button type="button" className={view === 'feed' ? 'active' : ''} aria-current={view === 'feed' ? 'page' : undefined} onClick={() => setView('feed')}>Activity & posts</button><button type="button" className={view === 'space' ? 'active' : ''} aria-current={view === 'space' ? 'page' : undefined} onClick={() => setView('space')}>Conversation Space <span>{graphPosts.length}</span></button></nav>
    {view === 'feed' ? <main id="seq-main" className="seq-layout">
      <aside className="seq-sidebar"><Timeline buckets={activityBuckets} selectedDay={selectedDay} onSelect={chooseDay} kind={run.streamSource === 'cache' ? 'saved' : run.kind} scaleMax={activityScale === 'day' ? run.activityScaleMax : undefined} query={run.query} scale={activityScale} onScaleChange={setActivityScale} loading={activityLoading} error={activityError} sample={activityScale === 'hour' && run.kind === 'saved'} />
        <ContextCard plan={run.searchPlan} />
        <section className="seq-sidebar-note"><p className="seq-sidebar-note-title">A slice of the discussion</p><p>{run.note}</p><button onClick={() => setShowData(true)}>See scope and sources <ArrowRight size={13} /></button></section>
        {run.model?.openai && <section className="seq-model-trace"><p>{run.kind === 'saved' ? 'RECORDED MODEL RUN' : 'POWERED BY'}</p><span>OpenAI <small>{run.model.openai}</small></span><span>Baseten <small>{basetenLabel}</small></span></section>}
      </aside>
      <section className="seq-feed" aria-label="Posts from selected day"><div className="seq-feed-head"><div><p>Conversation on</p><h2>{formatDay(selectedDay)} <small>UTC</small></h2></div><div className="seq-feed-actions"><button className={sort === 'relevance' ? 'active' : ''} onClick={() => setSort('relevance')}>Sequitor</button><button className={sort === 'popular' ? 'active' : ''} onClick={() => setSort('popular')}>Popular</button><button className={sort === 'recent' ? 'active' : ''} onClick={() => setSort('recent')}>Recent</button></div></div>
        <div className="seq-feed-status"><span>{run.id === sevenPostFallback.id ? 'Selected saved posts' : feedCoverage}</span><span>{shownLabel}</span></div>
        {busyLabel && <div className="seq-stream-status" role="status" aria-live="polite"><span className="seq-stream-pulse" /><span>{busyLabel}</span><span className="seq-stream-count">{periodPosts.length ? `${periodPosts.length} retrieved` : 'Waiting for the first results'}</span><button type="button" onClick={stopInvestigation}>Stop</button></div>}
        {!busyLabel && (runStatus === 'stopped' || runStatus === 'failed') && <p className="seq-stream-status" role="status">Investigation {runStatus}. Any retrieved posts are retained.</p>}
        {visible.length ? <div className="seq-post-list">{visible.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</div> : busyLabel ? <div className="seq-stream-skeleton" aria-hidden="true"><i /><i /><i /></div> : <div className="seq-empty"><Clock3 size={21} /><h3>No retrieved posts for this day</h3><p>The count can include posts that were not fetched for this feed. Choose another day or try a different seed.</p></div>}
        {!busyLabel && discoveries.length > 0 && <section className="seq-offshoots"><div className="seq-offshoots-heading"><Sparkles size={17} /><div><h3>A different turn</h3><p>Related replies and reactions beyond the ten posts above</p></div></div>{discoveries.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</section>}
        <div className="seq-feed-bottom"><span>{run.id === sevenPostFallback.id ? 'Selected source capture' : typeof run.xSpend === 'number' ? `${run.kind === 'saved' ? 'Estimated X spend at capture' : 'Estimated X spend in this server'}: $${run.xSpend.toFixed(2)}` : 'Estimated X spend not reported'}</span><span>Likes reflect collection time, not the selected day.</span></div>
      </section>
    </main> : <main id="seq-main"><ConversationSpace key={run.id} posts={graphPosts} seedId={graphSeedId}
      referencePosts={graphSeedId === storyCapture.seedId ? recordedReferencePosts : undefined}
      onOpenPost={setInspect} /></main>}
    <footer className="seq-footer"><Wordmark /><span>Explore the posts. Keep the limits in view.</span><button onClick={() => setShowData(true)}>Method and sources <ArrowUpRight size={13} /></button></footer>
    {inspect && <Context key={`${run.id}:${inspect.id}`} post={graphPosts.find(post => post.id === inspect.id) || inspect} posts={graphPosts} onClose={() => setInspect(null)} />}
    {showData && <Drawer title="About this view" label="About the data" closeLabel="Close data details" onClose={() => setShowData(false)}><div className="seq-drawer-content seq-info-drawer"><h3>What the bars count</h3><p>{run.note}</p><p><strong>Scope:</strong> {run.scope}{run.query ? ` · ${run.query}` : ''}</p><h3>What the feed contains</h3><p>{rankingCoverage}. {rankDescription} The feed excludes native retweet copies and can include an explicitly marked related search outside the measured phrase.</p><h3>Models in this run</h3><p><strong>OpenAI:</strong> {run.model?.openai || 'not run'}. It plans bounded literal searches from the seed text.</p><p><strong>Baseten:</strong> {basetenLabel}. It groups or compares retrieved posts; it does not determine truth, copying, or popularity.</p>{run.searchPlan?.discoveryPhrase && <p><strong>Related query:</strong> {run.searchPlan.discoveryPhrase}. {run.searchPlan.whyDiscovery}</p>}<h3>Source fidelity</h3><p>Post text and IDs come from X responses or the saved source snapshot. An earlier post, similar wording, or quote does not by itself prove who influenced whom.</p><p className="seq-data-time"><Check size={14} /> Captured {run.capturedAt ? formatTime(run.capturedAt) : 'at an unknown time'}</p></div></Drawer>}
  </div>
}
