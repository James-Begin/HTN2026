import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowLeft, ArrowRight, ArrowUpRight, BarChart3, Check, Clock3, Heart, Info, Link2, LoaderCircle, Search, Sparkles, X } from 'lucide-react'
import snapshot from '../../demo/recordings/pace-the-frontier/snapshot.json'
import liveCapture from '../../demo/recordings/sequitor-live.json'
import './sequitor.css'

type Post = {
  id: string; text: string; publishedAt: string; author: string; handle?: string
  avatar?: string; likes?: number | null; reposts?: number | null; replies?: number | null
  url?: string; parentId?: string | null; quotedPostId?: string | null
  scope?: string; captureTime?: string; textIsExcerpt?: boolean
  basetenKind?: string; sameClaimScore?: number; sameClaimRegister?: string
  basetenPick?: boolean
}
type Bucket = { day: string; count: number; coverage: 'complete' | 'partial' | 'sample' }
type Run = {
  id: string; seed: string; title: string; kind: 'live' | 'saved'; capturedAt?: string
  scope: string; query?: string | null; buckets: Bucket[]; posts: Post[]; selectedDay: string
  rankingCoverage: string; searchPlan?: { volumePhrase?: string; discoveryPhrase?: string | null; whyDiscovery?: string; model?: string | null; error?: string } | null
  model?: { openai?: string | null; baseten?: { status?: string; model?: string | null; classified?: number } | string }
  note: string; xSpend?: number
  savedPeriods?: Record<string, PeriodResult>
}
type PeriodResult = { day: string; posts: Post[]; rankingCoverage: string; partial: boolean; xSpend: number; model: Run['model'] }

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
const fallback: Run = {
  ...(liveCapture as Run), kind: 'saved',
  scope: 'Recorded X counts and retrieved posts',
  note: `Saved run captured ${formatTime(liveCapture.capturedAt)}. Its bars were measured on X at capture time; post lists cover retrieved candidates only.`,
}

function formatDay(day: string, withYear = true) {
  const date = new Date(`${day}T12:00:00Z`)
  return new Intl.DateTimeFormat('en-CA', { day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC' }).format(date)
}
function formatTime(iso: string) {
  if (!iso || Number.isNaN(Date.parse(iso))) return 'Time unavailable'
  return new Intl.DateTimeFormat('en-CA', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' }).format(new Date(iso))
}
function shortNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Intl.NumberFormat('en', { notation: value >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value)
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

function Timeline({ buckets, selectedDay, onSelect, kind }: { buckets: Bucket[]; selectedDay: string; onSelect: (day: string) => void; kind: Run['kind'] }) {
  const max = Math.max(1, ...buckets.map(bucket => bucket.count))
  const selected = buckets.find(bucket => bucket.day === selectedDay)
  const isSample = buckets.some(bucket => bucket.coverage === 'sample')
  return <section className="seq-timeline" aria-label="Activity over time">
    <div className="seq-section-top"><div><h2>Activity over time</h2><p>{isSample ? 'Selected saved posts' : 'X posts matching the measured phrase'}</p></div><BarChart3 size={18} aria-hidden="true" /></div>
    <div className="seq-activity-total"><strong>{shortNumber(selected?.count)}</strong><span>posts on {formatDay(selectedDay)} <span className="seq-utc">UTC</span></span></div>
    <div className="seq-chart" role="group" aria-label="Choose a day">
      {buckets.map(bucket => <button key={bucket.day} type="button" className={`seq-bar ${bucket.day === selectedDay ? 'is-selected' : ''} ${bucket.coverage !== 'complete' ? 'is-partial' : ''}`}
        style={{ height: `${Math.max(9, Math.sqrt(bucket.count / max) * 100)}%` }}
        title={`${formatDay(bucket.day)}: ${bucket.count.toLocaleString()} ${bucket.coverage === 'sample' ? 'saved' : 'matching'} posts`}
        aria-label={`${formatDay(bucket.day)}: ${bucket.count.toLocaleString()} ${bucket.coverage === 'sample' ? 'saved' : 'matching'} posts`}
        aria-pressed={bucket.day === selectedDay} onClick={() => onSelect(bucket.day)}><span className="sr-only">{formatDay(bucket.day)}</span></button>)}
    </div>
    <div className="seq-chart-axis"><span>{buckets.length ? formatDay(buckets[0].day, false) : ''}</span><span>{buckets.length ? formatDay(buckets[buckets.length - 1].day, false) : ''}</span></div>
    <p className="seq-timeline-foot">{isSample ? 'Sample counts · not platform activity' : `One exact phrase · retweets included · ${kind === 'saved' ? 'saved measurement' : 'live measurement'}`}{selected?.coverage === 'partial' ? ' · partial coverage' : ''}</p>
  </section>
}

function PostRow({ post, onOpen }: { post: Post; onOpen: (post: Post) => void }) {
  const displayAuthor = post.author.replace(/\s*·\s*@\S+$/, '')
  const showHandle = post.handle && displayAuthor.toLowerCase() !== `@${post.handle}`.toLowerCase()
  const initials = displayAuthor.replace(/^@/, '').slice(0, 2).toUpperCase()
  return <article className="seq-post">
    <button className="seq-avatar" onClick={() => onOpen(post)} aria-label={`Open context for ${post.author}`}>{post.avatar ? <img src={post.avatar} alt="" loading="lazy" /> : initials}</button>
    <div className="seq-post-body">
      <div className="seq-post-head"><div><strong>{displayAuthor}</strong>{showHandle && <span>@{post.handle}</span>}</div><time dateTime={post.publishedAt}>{formatTime(post.publishedAt)}</time></div>
      <p className="seq-post-text">{post.text}</p>
      {post.textIsExcerpt && <span className="seq-post-notice">Captured excerpt; full text unavailable here</span>}
      <div className="seq-post-foot">
        <span>{post.scope === 'broader discovery' ? <><Sparkles size={12} /> Related search</> : post.scope === 'direct conversation' ? 'Direct reply or thread' : post.scope === 'saved source' ? 'Saved source' : post.scope === 'seed' ? 'Starting post' : null}</span>
        <div>{post.likes !== undefined && post.likes !== null && <span title={`Likes captured ${post.captureTime || 'when retrieved'}`}><Heart size={14} /> {shortNumber(post.likes)}</span>}
          <button onClick={() => onOpen(post)}>Context <ArrowRight size={13} /></button>
          {post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${post.author}'s post on X`}><ArrowUpRight size={16} /></a>}</div>
      </div>
    </div>
  </article>
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
  const [sort, setSort] = useState<'popular' | 'recent'>('popular')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [inspect, setInspect] = useState<Post | null>(null)
  const [showData, setShowData] = useState(false)
  const [health, setHealth] = useState<boolean | null>(null)
  const requestId = useRef(0)

  useEffect(() => {
    getJson<Run>('/api/demo').then(demo => { setRun(demo); setSelectedDay(demo.selectedDay); setPeriodPosts(demo.posts); setRankingCoverage(demo.rankingCoverage); setHealth(true) })
      .catch(() => setHealth(false))
  }, [])

  async function explore(event?: FormEvent) {
    event?.preventDefault()
    const id = ++requestId.current
    setBusy('Reading the seed and planning a bounded search…'); setError('')
    try {
      const response = await fetch('/api/explore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seed: seed.trim() || defaultSeed }) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || 'Live exploration failed')
      if (id !== requestId.current) return
      setRun(data as Run); setSelectedDay(data.selectedDay); setPeriodPosts(data.posts)
      setRankingCoverage(data.rankingCoverage); setBusy(''); setHealth(true)
    } catch (cause) {
      if (id !== requestId.current) return
      setBusy(''); setError(cause instanceof Error ? cause.message : 'Live exploration failed')
    }
  }

  async function chooseDay(day: string) {
    const id = ++requestId.current
    setSelectedDay(day); setError('')
    if (run.kind === 'saved') {
      setPeriodPosts(run.savedPeriods?.[day]?.posts || (run.id === sevenPostFallback.id ? sevenPostFallback.posts : run.posts))
      setRankingCoverage(run.savedPeriods?.[day]?.rankingCoverage || 'No posts saved for this date')
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
    return [...dayPosts].sort((a, b) => sort === 'popular'
      ? (b.likes ?? -1) - (a.likes ?? -1) || a.id.localeCompare(b.id)
      : b.publishedAt.localeCompare(a.publishedAt)).slice(0, 10)
  }, [periodPosts, selectedDay, sort])
  const discoveries = useMemo(() => {
    const visibleIds = new Set(visible.map(post => post.id))
    return periodPosts.filter(post => post.publishedAt?.startsWith(selectedDay) && !visibleIds.has(post.id)
      && post.text.replace(/https?:\/\/\S+/g, '').trim().length >= 35
      && (post.basetenPick || post.scope === 'broader discovery' || post.scope === 'direct conversation'
        || ['joke', 'criticism', 'question'].includes(post.basetenKind || '')))
      .sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1)).slice(0, 3)
  }, [periodPosts, selectedDay, visible])
  const baseten = run.model?.baseten
  const basetenLabel = typeof baseten === 'string' ? baseten : baseten?.status || 'not run'

  return <div className="seq-shell">
    <a className="seq-skip" href="#seq-main">Skip to posts</a>
    <header className="seq-topbar"><Wordmark /><span className="seq-topbar-right"><span className={`seq-live-dot ${run.kind === 'saved' ? 'is-saved' : ''}`} />{run.kind === 'saved' ? 'Recorded X activity' : 'Live X activity'}<button onClick={() => setShowData(true)} aria-label="About the data"><Info size={17} /></button></span></header>
    <div className="seq-intro"><div><h1>Follow the conversation.</h1><p>See when a post took off, what people said, and where it went next.</p></div>
      {health === true ? <form className="seq-search" onSubmit={explore}><Link2 size={17} aria-hidden="true" /><input aria-label="X post URL or topic" value={seed} onChange={event => setSeed(event.target.value)} placeholder="Paste an X post URL or topic" /><button type="submit" disabled={Boolean(busy)}>{busy ? <LoaderCircle size={16} className="seq-spin" /> : <Search size={16} />}<span>Explore live</span></button></form>
        : <a className="seq-recorded-cta" href="#seq-main">Explore the recorded run <ArrowRight size={17} /></a>}
    </div>
    {error && <div className="seq-error" role="alert">{error} <button onClick={() => setError('')}>Dismiss</button></div>}
    <div className="seq-investigation-head"><div><span className="seq-investigation-caption">CURRENT CONVERSATION</span><h2>{run.title.split(':')[0]}</h2><p>{run.kind === 'saved' ? 'A recorded conversation you can explore offline.' : 'Measured search, with original posts kept in view.'}</p></div><button className="seq-data-button" onClick={() => setShowData(true)}>About this data <ArrowUpRight size={15} /></button></div>
    <main id="seq-main" className="seq-layout">
      <aside className="seq-sidebar"><Timeline buckets={run.buckets} selectedDay={selectedDay} onSelect={chooseDay} kind={run.kind} />
        <section className="seq-sidebar-note"><p className="seq-sidebar-note-title">A slice of the discussion</p><p>{run.note}</p><button onClick={() => setShowData(true)}>See scope and sources <ArrowRight size={13} /></button></section>
        {run.model?.openai && <section className="seq-model-trace"><p>{run.kind === 'saved' ? 'RECORDED MODEL RUN' : 'POWERED BY'}</p><span>OpenAI <small>{run.model.openai}</small></span><span>Baseten <small>{basetenLabel}</small></span></section>}
      </aside>
      <section className="seq-feed" aria-label="Posts from selected day"><div className="seq-feed-head"><div><p>Conversation on</p><h2>{formatDay(selectedDay)} <small>UTC</small></h2></div><div className="seq-feed-actions"><button className={sort === 'popular' ? 'active' : ''} onClick={() => setSort('popular')}>Popular</button><button className={sort === 'recent' ? 'active' : ''} onClick={() => setSort('recent')}>Recent</button></div></div>
        <div className="seq-feed-status"><span>{run.id === sevenPostFallback.id ? 'Selected saved posts' : rankingCoverage}</span><span>{visible.length} shown</span></div>
        {busy ? <div className="seq-loading" role="status"><LoaderCircle size={22} className="seq-spin" />{busy}<span>One bounded request at a time.</span></div> : visible.length ? <div className="seq-post-list">{visible.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</div> : <div className="seq-empty"><Clock3 size={21} /><h3>No retrieved posts for this day</h3><p>The count can include posts that were not fetched for this feed. Choose another day or try a different seed.</p></div>}
        {!busy && discoveries.length > 0 && <section className="seq-offshoots"><div className="seq-offshoots-heading"><Sparkles size={17} /><div><h3>A different turn</h3><p>Related replies and reactions beyond the ten posts above</p></div></div>{discoveries.map(post => <PostRow key={post.id} post={post} onOpen={setInspect} />)}</section>}
        <div className="seq-feed-bottom"><span>{run.id === sevenPostFallback.id ? 'Selected source capture' : `${run.kind === 'saved' ? 'Estimated X spend at capture' : 'Estimated X spend in this server'}: $${(run.xSpend || 0).toFixed(2)}`}</span><span>Likes reflect collection time, not the selected day.</span></div>
      </section>
    </main>
    <footer className="seq-footer"><Wordmark /><span>Explore the posts. Keep the limits in view.</span><button onClick={() => setShowData(true)}>Method and sources <ArrowUpRight size={13} /></button></footer>
    {inspect && <Context post={inspect} posts={periodPosts} onClose={() => setInspect(null)} />}
    {showData && <div className="seq-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setShowData(false) }}><aside className="seq-drawer seq-info-drawer" aria-label="About the data"><div className="seq-drawer-head"><button onClick={() => setShowData(false)}><ArrowLeft size={16} /> Back</button><h2>About this view</h2><button className="seq-icon" onClick={() => setShowData(false)} aria-label="Close data details"><X size={18} /></button></div><div className="seq-drawer-content"><h3>What the bars count</h3><p>{run.note}</p><p><strong>Scope:</strong> {run.scope}{run.query ? ` · ${run.query}` : ''}</p><h3>What the feed contains</h3><p>{rankingCoverage}. Posts are sorted by likes recorded at collection time. The feed excludes native retweet copies and can include an explicitly marked related search outside the measured phrase.</p><h3>Models in this run</h3><p><strong>OpenAI:</strong> {run.model?.openai || 'not run'}. It plans bounded literal searches from the seed text.</p><p><strong>Baseten:</strong> {basetenLabel}. It groups or compares retrieved posts; it does not determine truth, copying, or popularity.</p>{run.searchPlan?.discoveryPhrase && <p><strong>Related query:</strong> {run.searchPlan.discoveryPhrase}. {run.searchPlan.whyDiscovery}</p>}<h3>Source fidelity</h3><p>Post text and IDs come from X responses or the saved source snapshot. An earlier post, similar wording, or quote does not by itself prove who influenced whom.</p><p className="seq-data-time"><Check size={14} /> Captured {run.capturedAt ? formatTime(run.capturedAt) : 'at an unknown time'}</p></div></aside></div>}
  </div>
}
