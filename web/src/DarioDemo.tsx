import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { CalendarClock, Flag, Globe2, Image, ListChecks, MapPin, Search, SkipForward, Smile } from 'lucide-react'
import liveCapture from '../../demo/recordings/sequitor-live.json'
import humorCapture from '../../demo/recordings/dario-humor.json'
import ConversationSpace from './ConversationSpace'
import ConversationSidebar, { type ConversationSidebarPost } from './ConversationSidebar'
import SearchIntro from './SearchIntro'
import type { GraphPost } from './graphData'
import { useConversationReveal } from './useConversationReveal'
import './dario-demo.css'

type DarioPost = GraphPost & ConversationSidebarPost & { textIsExcerpt?: boolean }
type DarioRun = { seed: string; buckets: { day: string; count: number | null }[]; posts: DarioPost[]; seedPost?: DarioPost; savedPeriods?: Record<string, { posts: DarioPost[] }>; searchPlan?: { contextLabel?: string; entities?: string[] } }
type DemoStage = 'landing' | 'searching' | 'resolving' | 'anchor' | 'forming' | 'exploring'
const capture = liveCapture as DarioRun
const humor = humorCapture.posts as DarioPost[]
const seed = capture.seedPost || capture.posts.find(post => post.id === '2098773920774074715')!
const allPosts = (() => {
  const values = [seed, ...capture.posts, ...Object.values(capture.savedPeriods || {}).flatMap(period => period.posts), ...humor]
  const unique = [...new Map(values.filter(post => post.id && post.text && post.publishedAt).map(post => [post.id, post])).values()]
  return [seed, ...unique.filter(post => post.id !== seed.id).sort((a, b) => (b.likes || 0) - (a.likes || 0) || a.publishedAt.localeCompare(b.publishedAt) || a.id.localeCompare(b.id))]
})()
const activityStart = Math.min(...allPosts.map(post => Date.parse(post.publishedAt)))
const activityEnd = Math.max(...allPosts.map(post => Date.parse(post.publishedAt)))
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

function ActivityStrip({ posts }: { posts: DarioPost[] }) {
  const [scale, setScale] = useState<'hour' | 'day' | 'month'>('day')
  const bars = useMemo(() => {
    const counts = new Map<number, number>()
    for (const post of posts) {
      const time = Date.parse(post.publishedAt)
      if (Number.isFinite(time)) counts.set(floorTime(time, scale), (counts.get(floorTime(time, scale)) || 0) + 1)
    }
    const items: { time: number; count: number }[] = []
    for (let time = floorTime(activityStart, scale), end = floorTime(activityEnd, scale); time <= end; time = addUnit(time, scale)) items.push({ time, count: counts.get(time) || 0 })
    return items
  }, [posts, scale])
  const chartMax = Math.max(1, ...bars.map(bucket => bucket.count))
  return <section className="dario-activity" aria-label="Activity over time"><div className="dario-activity-top"><strong>Activity over time</strong><div className="dario-activity-controls" role="group" aria-label="Activity resolution">
    {(['hour', 'day', 'month'] as const).map(value => <button key={value} type="button" aria-pressed={scale === value} onClick={() => setScale(value)}>{value === 'hour' ? 'Hour' : value === 'day' ? 'Day' : 'Month'}</button>)}
  </div></div><div className="dario-bars" aria-hidden="true">{bars.map(bucket => <i key={bucket.time} className={bucket.count ? 'is-visible' : ''} style={{ '--height': `${Math.sqrt(bucket.count / chartMax) * 100}%` } as CSSProperties} />)}</div><div className="dario-activity-axis"><span>{bars[0] ? labelTime(bars[0].time, scale) : ''}</span><span>{bars.length > 1 ? labelTime(bars[bars.length - 1].time, scale) : ''}</span></div></section>
}

export default function DarioDemo() {
  const [stage, setStage] = useState<DemoStage>('landing'), [input, setInput] = useState(''), [selectedId, setSelectedId] = useState(seed.id)
  const timers = useRef<number[]>([])
  const reveal = useConversationReveal(stage === 'forming' || stage === 'exploring' ? allPosts : [])
  const presented = (stage === 'anchor' ? [seed] : reveal.presentedPosts) as DarioPost[]
  const selected = presented.find(post => post.id === selectedId) || seed
  const clearTimers = useCallback(() => { timers.current.forEach(timer => window.clearTimeout(timer)); timers.current = [] }, [])
  const selectPost = useCallback((post: GraphPost) => setSelectedId(post.id), [])
  useEffect(() => clearTimers, [clearTimers])
  const launch = useCallback((query: string) => {
    const value = query.trim()
    if (!value) return
    clearTimers(); setInput(value); setSelectedId(seed.id); setStage('searching')
    timers.current.push(window.setTimeout(() => setStage('resolving'), 5400))
    timers.current.push(window.setTimeout(() => setStage('anchor'), 6350))
    timers.current.push(window.setTimeout(() => { setStage('forming'); window.setTimeout(reveal.reset, 0) }, 7600))
    timers.current.push(window.setTimeout(() => setStage('exploring'), 12000))
  }, [clearTimers, reveal.reset])
  const begin = useCallback((event: FormEvent) => {
    event.preventDefault()
    launch(input)
  }, [input, launch])
  const context = useMemo(() => ({ title: capture.searchPlan?.contextLabel || 'AI industry pacing and independent evaluation', entities: capture.searchPlan?.entities || ['Anthropic'] }), [])
  const status = stage === 'searching' || stage === 'resolving' ? 'searching' : reveal.isComplete ? 'complete' : 'building'
  if (stage === 'landing') return <main className="dario-landing">
    <div className="dario-landing-wordmark" aria-label="Sequitor">sequitor<span>.</span></div>
    <section className="dario-composer" aria-label="Start a conversation search">
      <div className="dario-composer-tab" aria-hidden="true"><span /></div>
      <form onSubmit={begin}>
        <div className="dario-composer-body">
          <span className="dario-composer-avatar" aria-hidden="true">
            <span>S</span>
            {seed.avatar && <img src={seed.avatar} alt="" onError={event => { event.currentTarget.style.display = 'none' }} />}
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
          <button className="dario-composer-submit" type="submit" disabled={!input.trim()}>Explore</button>
        </div>
      </form>
    </section>
    <button className="dario-example" type="button" onClick={() => launch(capture.seed)}>Try Dario’s post</button>
  </main>
  if (stage === 'searching' || stage === 'resolving') return <main className="dario-transition"><SearchIntro phase={stage === 'searching' ? 'searching' : 'resolving'} /></main>
  const cinematic = stage === 'anchor' || stage === 'forming'
  return <main className={`dario-demo${cinematic ? ' is-cinematic' : ' is-exploring'}`}><header className="dario-header"><div className="dario-wordmark">sequitor<span>.</span></div><form onSubmit={begin} className="dario-header-search"><Search size={15} aria-hidden="true" /><input aria-label="Dario example post URL" value={input} onChange={event => setInput(event.target.value)} /><button type="submit">New search</button></form></header><section className="dario-workspace" aria-label="Dario conversation"><div className="dario-viewer-column"><ConversationSpace posts={presented as GraphPost[]} seedId={seed.id} referencePosts={allPosts as GraphPost[]} compact cinematic={cinematic} onOpenPost={() => undefined} onSelectPost={selectPost} /><ActivityStrip posts={presented} />{stage === 'exploring' && !reveal.isComplete && <button type="button" className="dario-skip" onClick={reveal.skip}>Show all <SkipForward size={14} /></button>}</div><ConversationSidebar posts={presented} selectedPost={selected} referenceId={seed.id} onSelect={setSelectedId} context={context} status={status} /></section></main>
}
