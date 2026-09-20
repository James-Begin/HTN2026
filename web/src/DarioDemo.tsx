import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { CalendarClock, Flag, Globe2, Image, ListChecks, MapPin, SkipForward, Smile } from 'lucide-react'
import liveCapture from '../../demo/recordings/sequitor-live.json'
import humorCapture from '../../demo/recordings/dario-humor.json'
import tomdaleCapture from '../../demo/recordings/anchor-tomdale.json'
import drewhahnCapture from '../../demo/recordings/anchor-drewhahn.json'
import elonCapture from '../../demo/recordings/anchor-elon-dario.json'
import ConversationSpace from './ConversationSpace'
import ConversationSidebar, { type ConversationSidebarPost } from './ConversationSidebar'
import SearchIntro from './SearchIntro'
import type { GraphPost } from './graphData'
import type { Bucket, Run, RunMode } from './investigation/types'
import { useInvestigationRun } from './investigation/useInvestigationRun'
import { useConversationReveal } from './useConversationReveal'
import './dario-demo.css'
import './landing.css'
import htnLogo from '../public/htn-logo.svg?inline'

type DarioPost = GraphPost & ConversationSidebarPost & { textIsExcerpt?: boolean }
type DarioRun = Omit<Run, 'posts' | 'seedPost' | 'savedPeriods'> & {
  posts: DarioPost[]
  seedPost?: DarioPost
  entryPost?: DarioPost
  savedPeriods?: Record<string, { posts: DarioPost[] }>
  anchorMethod?: string
}
type DemoStage = 'landing' | 'departing' | 'searching' | 'resolving' | 'blackout' | 'anchor' | 'forming' | 'exploring'
const capture = liveCapture as unknown as DarioRun
const humor = humorCapture.posts as DarioPost[]
const DARIO_ID = '2098773920774074715'
const RECORDED_IDS = new Set([DARIO_ID, '2098435855857668156', '2085392809385988130', '2098789109980332057'])
const EXAMPLES = [
  { id: DARIO_ID, url: 'https://x.com/DarioAmodei/status/2098773920774074715', label: 'Try Dario’s post' },
]
const recordedSeed = capture.seedPost || capture.posts.find(post => post.id === DARIO_ID)!
const recordedPosts = (() => {
  const values = [recordedSeed, ...capture.posts, ...Object.values(capture.savedPeriods || {}).flatMap(period => period.posts), ...humor]
  const unique = [...new Map(values.filter(post => post.id && post.text && post.publishedAt).map(post => [post.id, post])).values()]
  return [recordedSeed, ...unique.filter(post => post.id !== recordedSeed.id).sort((a, b) => (b.likes || 0) - (a.likes || 0) || a.publishedAt.localeCompare(b.publishedAt) || a.id.localeCompare(b.id))]
})()
const LOCAL_RECORDINGS: Record<string, DarioRun> = {
  [DARIO_ID]: { ...capture, kind: 'saved', streamSource: 'recorded', posts: recordedPosts },
  '2098435855857668156': tomdaleCapture as unknown as DarioRun,
  '2085392809385988130': drewhahnCapture as unknown as DarioRun,
  '2098789109980332057': (() => {
    const thin = elonCapture as unknown as DarioRun
    const values = [...recordedPosts, ...(thin.posts || []), thin.seedPost, thin.entryPost].filter(Boolean) as DarioPost[]
    const posts = [...new Map(values.filter(post => post.id).map(post => [post.id, post])).values()]
    return { ...thin, posts, buckets: (capture.buckets?.length ? capture.buckets : thin.buckets) as DarioRun['buckets'] }
  })(),
}
const floorTime = (stamp: number, unit: 'hour' | 'day' | 'month') => {
  const date = new Date(stamp)
  if (unit === 'month') return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)
  if (unit === 'day') return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), date.getUTCHours())
}
const addUnit = (stamp: number, unit: 'hour' | 'day' | 'month') => {
  const date = new Date(stamp)
  if (unit === 'month') return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)
  return stamp + (unit === 'hour' ? 3600000 : 86400000)
}
const labelTime = (stamp: number, unit: 'hour' | 'day' | 'month') => new Intl.DateTimeFormat('en-CA', unit === 'hour' ? { month: 'short', day: 'numeric', hour: 'numeric', timeZone: 'UTC' } : unit === 'month' ? { month: 'short', year: 'numeric', timeZone: 'UTC' } : { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(stamp))
const LAUNCH_AT = { searching: 1250, resolving: 7200, reducedSearching: 180 }
const BLACKOUT_HOLD_MS = 1200
const ANCHOR_HOLD_MS = 1200
const FORMING_HOLD_MS = 4200
const MIN_CONVERSATION_POSTS = 12

function ActivityStrip({ buckets, posts }: { buckets: Bucket[]; posts: DarioPost[] }) {
  const [scale, setScale] = useState<'hour' | 'day' | 'month'>('day')
  const bars = useMemo(() => {
    const counts = new Map<number, number>()
    if (buckets.length) {
      for (const bucket of buckets) {
        const time = Date.parse(bucket.day)
        if (Number.isFinite(time)) counts.set(floorTime(time, scale), (counts.get(floorTime(time, scale)) || 0) + (bucket.count || 0))
      }
    } else {
      for (const post of posts) {
        const time = Date.parse(post.publishedAt)
        if (Number.isFinite(time)) counts.set(floorTime(time, scale), (counts.get(floorTime(time, scale)) || 0) + 1)
      }
    }
    if (!counts.size) return []
    const activityStart = Math.min(...counts.keys())
    const activityEnd = Math.max(...counts.keys())
    const items: { time: number; count: number }[] = []
    for (let time = floorTime(activityStart, scale), end = floorTime(activityEnd, scale); time <= end; time = addUnit(time, scale)) items.push({ time, count: counts.get(time) || 0 })
    return items
  }, [buckets, posts, scale])
  const chartMax = Math.max(1, ...bars.map(bucket => bucket.count))
  return <section className="dario-activity" aria-label="Activity over time"><div className="dario-activity-top"><strong>Activity over time</strong><div className="dario-activity-controls" role="group" aria-label="Activity resolution">
    {(['hour', 'day', 'month'] as const).map(value => <button key={value} type="button" aria-pressed={scale === value} onClick={() => setScale(value)}>{value === 'hour' ? 'Hour' : value === 'day' ? 'Day' : 'Month'}</button>)}
  </div></div><div className="dario-bars" aria-hidden="true">{bars.map(bucket => <i key={bucket.time} className={bucket.count ? 'is-visible' : ''} style={{ '--height': `${Math.sqrt(bucket.count / chartMax) * 100}%` } as CSSProperties} />)}</div><div className="dario-activity-axis"><span>{bars[0] ? labelTime(bars[0].time, scale) : ''}</span><span>{bars.length > 1 ? labelTime(bars[bars.length - 1].time, scale) : ''}</span></div></section>
}

export default function DarioDemo() {
  const investigation = useInvestigationRun()
  const [stage, setStage] = useState<DemoStage>('landing'), [input, setInput] = useState(''), [selectedId, setSelectedId] = useState('')
  const [runMode, setRunMode] = useState<RunMode | null>(null)
  const [entryId, setEntryId] = useState('')
  const [fallbackRun, setFallbackRun] = useState<DarioRun | null>(null)
  const [timerReady, setTimerReady] = useState({ searching: false, resolving: false, anchor: false, forming: false, exploring: false })
  const [introFinished, setIntroFinished] = useState(false)
  const [sidebarActive, setSidebarActive] = useState(false)
  const timers = useRef<number[]>([])
  const stageRef = useRef(stage)
  stageRef.current = stage
  const run = fallbackRun || investigation.run
  const resolvedSeed = (fallbackRun?.seedPost || investigation.seedPost || run?.seedPost) as DarioPost | undefined
  const streamPosts = useMemo(() => {
    const source = fallbackRun
      ? ((fallbackRun.posts?.length ? fallbackRun.posts : recordedPosts) as DarioPost[])
      : investigation.posts as DarioPost[]
    return source.filter(post => Number.isFinite(Date.parse(post.publishedAt)))
  }, [fallbackRun, investigation.posts])
  const seedPost = resolvedSeed && Number.isFinite(Date.parse(resolvedSeed.publishedAt)) ? resolvedSeed : streamPosts[0]
  const allPosts = useMemo(() => {
    const values = [...(seedPost ? [seedPost] : []), ...streamPosts]
    return [...new Map(values.map(post => [post.id, post])).values()].sort(
      (a, b) => a.publishedAt.localeCompare(b.publishedAt) || a.id.localeCompare(b.id),
    )
  }, [seedPost, streamPosts])
  const revealing = stage === 'forming' || stage === 'exploring'
  const reveal = useConversationReveal(revealing ? allPosts : stage === 'anchor' && seedPost ? [seedPost] : [])
  const presented = useMemo(() => {
    if (stage === 'anchor') return seedPost ? [seedPost] : []
    const posts = reveal.presentedPosts as DarioPost[]
    if (revealing && seedPost && !posts.some(post => post.id === seedPost.id)) return [seedPost, ...posts]
    return posts
  }, [stage, revealing, reveal.presentedPosts, seedPost])
  const sidebarReveal = useConversationReveal(sidebarActive ? presented : [])
  const sidebarPosts = sidebarReveal.presentedPosts as DarioPost[]
  const sidebarSelected = sidebarPosts.find(post => post.id === selectedId) || sidebarPosts.find(post => post.id === seedPost?.id)
  const clearTimers = useCallback(() => { timers.current.forEach(timer => window.clearTimeout(timer)); timers.current = [] }, [])
  const finishIntro = useCallback(() => setIntroFinished(true), [])
  const selectPost = useCallback((post: GraphPost) => setSelectedId(post.id), [])
  useEffect(() => clearTimers, [clearTimers])
  useEffect(() => {
    if (seedPost) setSelectedId(current => current || seedPost.id)
  }, [seedPost])
  useEffect(() => {
    const recordedReady = runMode === 'recorded' && (investigation.milestones.runReady || !!fallbackRun)
    const started = investigation.milestones.started || recordedReady
    const resolved = investigation.milestones.seedResolved || investigation.milestones.planReady || recordedReady
    const conversationPostCount = streamPosts.filter(post => post.id !== seedPost?.id).length
    const terminal = ['completed', 'failed', 'stopped'].includes(investigation.status)
    const conversationReady = !!fallbackRun
      || investigation.milestones.runReady && (conversationPostCount >= MIN_CONVERSATION_POSTS || terminal)
    if (stage === 'departing' && timerReady.searching && started) setStage('searching')
    else if (stage === 'searching' && timerReady.resolving && resolved && conversationReady) setStage('resolving')
    else if (stage === 'resolving' && introFinished) setStage('blackout')
    else if (stage === 'blackout' && timerReady.anchor && seedPost) setStage('anchor')
    else if (stage === 'anchor' && timerReady.forming && seedPost) setStage('forming')
    else if (stage === 'forming' && timerReady.exploring) setStage('exploring')
  }, [fallbackRun, investigation.milestones, investigation.status, introFinished, runMode, seedPost, stage, streamPosts, timerReady])
  useEffect(() => {
    if (stage !== 'blackout') return
    const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : BLACKOUT_HOLD_MS
    const timer = window.setTimeout(() => setTimerReady(previous => ({ ...previous, anchor: true })), delay)
    return () => window.clearTimeout(timer)
  }, [stage])
  useEffect(() => {
    if (stage !== 'anchor') return
    const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : ANCHOR_HOLD_MS
    const timer = window.setTimeout(() => setTimerReady(previous => ({ ...previous, forming: true })), delay)
    return () => window.clearTimeout(timer)
  }, [stage])
  useEffect(() => {
    if (stage !== 'forming') return
    const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : FORMING_HOLD_MS
    const timer = window.setTimeout(() => setTimerReady(previous => ({ ...previous, exploring: true })), delay)
    return () => window.clearTimeout(timer)
  }, [stage])
  useEffect(() => {
    if (stage !== 'exploring') {
      setSidebarActive(false)
      return
    }
    const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 7900
    const timer = window.setTimeout(() => setSidebarActive(true), delay)
    return () => window.clearTimeout(timer)
  }, [stage])
  useEffect(() => {
    if (sidebarActive) sidebarReveal.reset()
  }, [sidebarActive, sidebarReveal.reset])
  const launch = useCallback((query: string) => {
    const value = query.trim()
    if (!value || stageRef.current !== 'landing') return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const statusId = value.match(/\/(?:status|statuses)\/(\d+)/i)?.[1] || ''
    const mode: RunMode = RECORDED_IDS.has(statusId) ? 'recorded' : 'live'
    clearTimers(); setInput(value); setSelectedId(''); setEntryId(statusId); setRunMode(mode); setFallbackRun(null); setIntroFinished(false)
    setTimerReady({ searching: false, resolving: false, anchor: false, forming: false, exploring: false })
    setStage('departing')
    const mark = (key: keyof typeof timerReady) => setTimerReady(previous => ({ ...previous, [key]: true }))
    timers.current.push(window.setTimeout(() => mark('searching'), reduced ? LAUNCH_AT.reducedSearching : LAUNCH_AT.searching))
    timers.current.push(window.setTimeout(() => mark('resolving'), LAUNCH_AT.resolving))
    void investigation.start({ seed: value, mode }).then(started => {
      if (!started && mode === 'recorded' && stageRef.current !== 'landing') {
        const local = LOCAL_RECORDINGS[statusId]
        if (local) setFallbackRun(local)
      }
    })
  }, [clearTimers, investigation.start])
  const begin = useCallback((event: FormEvent) => {
    event.preventDefault()
    launch(input)
  }, [input, launch])
  const context = useMemo(() => ({ title: run?.searchPlan?.contextLabel, entities: run?.searchPlan?.entities }), [run?.searchPlan])
  const introPosts = useMemo(() => {
    if (runMode === 'recorded') {
      const recorded = LOCAL_RECORDINGS[entryId]
      if (recorded?.posts?.length) return recorded.posts
    }
    return streamPosts
  }, [entryId, runMode, streamPosts])
  const error = fallbackRun ? '' : investigation.error
  const status = error ? 'error' : stage === 'searching' || stage === 'resolving' ? 'searching' : reveal.isComplete ? 'complete' : 'building'
  if (stage === 'landing' || stage === 'departing') return <main className={`dario-landing${stage === 'departing' ? ' is-departing' : ''}`} data-demo-stage={stage}>
    <div className="dario-landing-wordmark" aria-label="Sequitor">sequitor<span>.</span></div>
    <section className="dario-composer" aria-label="Start a conversation search">
      <div className="dario-composer-tab" aria-hidden="true"><span /></div>
      <form onSubmit={begin}>
        <div className="dario-composer-body">
          <span className="dario-composer-avatar" aria-hidden="true">
            <img src={htnLogo} alt="" />
          </span>
          <div className="dario-composer-content">
            <textarea
              aria-label="Post URL or search query"
              autoFocus
              placeholder="What’s happening?"
              rows={3}
              value={input}
              onChange={event => setInput(event.target.value)}
            />
            <p className="dario-composer-audience"><Globe2 size={14} aria-hidden="true" /> Search across public posts</p>
          </div>
        </div>
        <div className="dario-composer-footer">
          <div className="dario-composer-tools" aria-hidden="true">
            <Image size={19} /><span className="dario-gif-tool">GIF</span><ListChecks size={19} /><Smile size={19} /><CalendarClock size={19} /><MapPin size={19} /><Flag size={19} />
          </div>
          <button className="dario-composer-submit" type="submit" disabled={!input.trim() || stage === 'departing'}>Explore</button>
        </div>
      </form>
    </section>
    <div className="dario-examples">
      {EXAMPLES.map(example => <button key={example.id} className="dario-example" type="button" onClick={() => launch(example.url)} disabled={stage === 'departing'}>{example.label}</button>)}
    </div>
    {error && <p className="dario-run-error" role="alert">{error}</p>}
  </main>
  if (stage === 'searching' || stage === 'resolving') return <main className="dario-transition is-intro-enter" data-demo-stage={stage}><SearchIntro key={`${runMode || 'live'}-${entryId || 'query'}`} phase={stage === 'searching' ? 'searching' : 'resolving'} posts={introPosts} canned={runMode === 'recorded'} onFinished={finishIntro} />{error && <p className="dario-run-error" role="alert">{error}</p>}</main>
  if (stage === 'blackout') return <main className="dario-transition" data-demo-stage="blackout">{error && <p className="dario-run-error" role="alert">{error}</p>}</main>
  const cinematic = stage === 'anchor' || stage === 'forming'
  const seedId = seedPost?.id || ''
  const anchorMethod = (run as DarioRun & { anchorMethod?: string } | null)?.anchorMethod || (seedId && entryId && seedId !== entryId ? 'walked' : 'self')
  return <main className={`dario-demo${cinematic ? ' is-cinematic' : ' is-exploring'}`} data-demo-stage={stage} data-presented-count={presented.length} data-seed-id={seedId} data-entry-id={entryId} data-run-mode={runMode || undefined} data-anchor-method={anchorMethod}><header className="dario-header"><div className="dario-wordmark">sequitor<span>.</span></div></header>{error && <p className="dario-run-error" role="alert">{error}</p>}<section className="dario-workspace" aria-label="Conversation investigation"><div className="dario-viewer-column"><ConversationSpace posts={presented as GraphPost[]} seedId={seedId} referencePosts={allPosts as GraphPost[]} compact cinematic={cinematic} onOpenPost={() => undefined} onSelectPost={selectPost} /><ActivityStrip buckets={run?.buckets || []} posts={presented} />{stage === 'exploring' && !reveal.isComplete && <button type="button" className="dario-skip" onClick={reveal.skip}>Show all <SkipForward size={14} /></button>}</div><ConversationSidebar posts={sidebarPosts} selectedPost={sidebarSelected} referenceId={seedId} onSelect={setSelectedId} context={context} status={status} /></section></main>
}
