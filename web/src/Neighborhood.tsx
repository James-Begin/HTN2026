import { useMemo, useState } from 'react'
import { ArrowUpRight, Focus, Link2, Minus, Plus, Search, X } from 'lucide-react'
import {
  buildObservedEdges, buildSemanticEdges, layoutStory, STORY_LANES,
  type GraphEdge, type GraphPost, type SemanticEdge, type StoryAnnotation,
} from './graphData'
import './neighborhood.css'

export type NeighborhoodProps = {
  posts: GraphPost[]
  seedId: string
  semanticEdges?: SemanticEdge[]
  referencePosts?: GraphPost[]
  selectedPostIds?: string[]
  annotations?: Record<string, StoryAnnotation>
  modelLabel?: string
  onOpenPost: (post: GraphPost) => void
}

type Layer = 'all' | 'reply' | 'quote' | 'semantic'

function easternDay(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Toronto', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  const value = (name: string) => parts.find(part => part.type === name)?.value || ''
  return `${value('year')}-${value('month')}-${value('day')}`
}

function shortDay(day: string) {
  return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }).format(new Date(`${day}T12:00:00Z`))
}

function localTime(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return 'Time unavailable'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Toronto', timeZoneName: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(date)
}

function nodeRadius(post: GraphPost | undefined, selected: boolean, focus: boolean) {
  if (focus) return 10
  if (selected) return 8
  return post?.scope === 'seed' ? 7 : 4.5
}

function initials(post: GraphPost) { return post.author.replace(/^@/, '').slice(0, 2).toUpperCase() }

function edgeSentence(edge: GraphEdge, byId: Map<string, GraphPost>) {
  const source = byId.get(edge.source)?.author || edge.source
  const target = byId.get(edge.target)?.author || edge.target
  if (edge.type === 'reply') return `${source} replied to ${target}. X records the referenced post ID.`
  if (edge.type === 'quote') return `${source} quoted ${target}. X records the referenced post ID.`
  return `${source} and ${target} share wording (TF-IDF cosine ${edge.cosine?.toFixed(2)}). ${edge.sharedTerms?.length ? `Shared terms: ${edge.sharedTerms.join(', ')}. ` : ''}This is a navigation clue, not proof of influence.`
}

export default function Neighborhood({ posts, seedId, referencePosts, selectedPostIds, annotations = {}, semanticEdges = [], modelLabel, onOpenPost }: NeighborhoodProps) {
  const [layer, setLayer] = useState<Layer>('all')
  const [throughDay, setThroughDay] = useState('all')
  const [focusId, setFocusId] = useState(seedId)
  const [selectedId, setSelectedId] = useState(seedId)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [zoom, setZoom] = useState(1)

  const allPosts = useMemo(() => [...new Map(posts.map(post => [post.id, post])).values()], [posts])
  const mapIds = useMemo(() => selectedPostIds ? new Set(selectedPostIds) : null, [selectedPostIds])
  const reference = useMemo(() => [...new Map((referencePosts || posts).filter(post => !mapIds || mapIds.has(post.id)).map(post => [post.id, post])).values()], [referencePosts, posts, mapIds])
  const days = useMemo(() => [...new Set(allPosts.map(post => easternDay(post.publishedAt)).filter(Boolean))].sort(), [allPosts])
  const dayPosts = useMemo(() => throughDay === 'all' ? allPosts
    : allPosts.filter(post => easternDay(post.publishedAt) <= throughDay), [allPosts, throughDay])
  const byId = useMemo(() => new Map(dayPosts.map(post => [post.id, post])), [dayPosts])
  const activeSelection = byId.has(selectedId) ? selectedId : byId.has(seedId) ? seedId : dayPosts[0]?.id
  const mappedPosts = useMemo(() => dayPosts.filter(post => !mapIds || mapIds.has(post.id) || post.id === activeSelection), [dayPosts, mapIds, activeSelection])
  const observed = useMemo(() => buildObservedEdges(mappedPosts), [mappedPosts])
  const semantic = useMemo(() => buildSemanticEdges(mappedPosts, semanticEdges), [mappedPosts, semanticEdges])
  const shownEdges = useMemo(() => [...observed, ...semantic].filter(edge => layer === 'all' || edge.type === layer), [observed, semantic, layer])
  const basePositions = useMemo(() => layoutStory(reference, annotations, seedId), [reference, annotations, seedId])
  const positions = useMemo(() => {
    const result = new Map(basePositions.map(node => [node.id, node]))
    for (const post of mappedPosts) {
      if (!result.has(post.id)) {
        const extra = layoutStory([...reference, post], annotations, seedId).find(node => node.id === post.id)
        if (extra) result.set(post.id, extra)
      }
    }
    return result
  }, [basePositions, mappedPosts, reference, annotations, seedId])
  const nodes = mappedPosts.map(post => positions.get(post.id)).filter(node => node !== undefined)
  const selected = activeSelection ? byId.get(activeSelection) : undefined
  const selectedEdge = selectedEdgeId ? shownEdges.find(edge => edge.id === selectedEdgeId) : undefined
  const relevant = useMemo(() => activeSelection ? shownEdges.filter(edge => edge.source === activeSelection || edge.target === activeSelection) : [], [activeSelection, shownEdges])
  const directSeedLinks = shownEdges.filter(edge => edge.type !== 'semantic' && (edge.source === seedId || edge.target === seedId))
  const drawnEdges = shownEdges.filter(edge => !directSeedLinks.includes(edge) || edge.id === selectedEdgeId || (activeSelection !== seedId && (edge.source === activeSelection || edge.target === activeSelection)))
  const earlier = relevant.filter(edge => edge.type !== 'semantic' && edge.source === activeSelection)
  const later = relevant.filter(edge => edge.type !== 'semantic' && edge.target === activeSelection)
  const similar = relevant.filter(edge => edge.type === 'semantic')
  const matches = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return []
    return dayPosts.filter(post => `${post.author} ${post.handle || ''} ${post.text}`.toLowerCase().includes(query))
      .sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 8)
  }, [dayPosts, search])
  const represented = new Set([...observed, ...semantic].flatMap(edge => [edge.source, edge.target]))
  const target = positions.get(focusId) || positions.get(activeSelection || '')
  const viewWidth = 1200 / zoom
  const viewHeight = 760 / zoom
  const viewX = zoom === 1 ? 0 : Math.max(0, Math.min(1200 - viewWidth, (target?.x || 600) - viewWidth / 2))
  const viewY = zoom === 1 ? 0 : Math.max(0, Math.min(760 - viewHeight, (target?.y || 380) - viewHeight / 2))

  function choosePost(id: string, center = false) {
    setSelectedId(id)
    setSelectedEdgeId(null)
    if (center) { setFocusId(id); setZoom(value => Math.max(value, 1.7)) }
    setSearch('')
  }

  return <section className="seq-neighborhood" aria-label="Conversation neighborhood">
    <div className="seq-neighborhood-head">
      <div><h2>Follow the story through the crowd.</h2><p>Time runs left to right. Rows group how posts speak: reporting, response, critique, or humor. Follow recorded references and compare shared wording.</p></div>
      <div className="seq-neighborhood-stats"><strong>{observed.length}</strong><span>recorded links</span><strong>{mappedPosts.length}</strong><span>mapped posts</span></div>
    </div>
    <div className="seq-neighborhood-controls">
      <div className="seq-neighborhood-layers" role="group" aria-label="Connection type">
        {([['all', 'All links'], ['reply', 'Replies'], ['quote', 'Quotes'], ['semantic', 'Shared wording']] as const).map(([value, label]) =>
          <button key={value} type="button" aria-pressed={layer === value} className={layer === value ? 'active' : ''}
            disabled={value === 'semantic' && semantic.length === 0}
            title={value === 'semantic' && semantic.length === 0 ? 'No measured wording links in this capture' : undefined}
            onClick={() => { setLayer(value); setSelectedEdgeId(null) }}>{label}</button>)}
      </div>
      <label className="seq-neighborhood-date"><span>Through</span><select value={throughDay} onChange={event => { setThroughDay(event.target.value); setSelectedEdgeId(null) }}>
        <option value="all">All captured days</option>{days.map(day => <option key={day} value={day}>{shortDay(day)} ET</option>)}
      </select></label>
    </div>
    <div className="seq-neighborhood-workspace">
      <div className="seq-neighborhood-map">
        <div className="seq-neighborhood-map-top"><span><span className="seq-neighborhood-live-dot" /> Story map · {mappedPosts.length} posts</span>
          <span>{directSeedLinks.length} direct seed links summarized in the inspector</span>
        </div>
        {nodes.length ? <svg className="seq-neighborhood-svg" viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`} role="img" aria-label={`Chronological map of ${nodes.length} posts and ${drawnEdges.length} drawn links; direct seed links can be inspected individually`}>
          <defs><filter id="seq-node-glow"><feGaussianBlur stdDeviation="5" /></filter></defs>
          {STORY_LANES.map((lane, index) => <g key={lane.label} className="seq-neighborhood-lane"><rect x="0" y={lane.y - 52} width="1200" height="104" className={index % 2 ? 'alternate' : ''} /><line x1="72" y1={lane.y + 52} x2="1200" y2={lane.y + 52} /><text x="17" y={lane.y - 31}>{lane.label}</text></g>)}
          <text x="90" y="741" className="seq-neighborhood-axis">EARLIER</text><text x="1145" y="741" textAnchor="end" className="seq-neighborhood-axis">LATER →</text>
          {drawnEdges.map(edge => {
            const a = positions.get(edge.source)
            const b = positions.get(edge.target)
            if (!a || !b) return null
            const active = selectedEdgeId === edge.id || (relevant.length <= 12 && !!activeSelection && (edge.source === activeSelection || edge.target === activeSelection))
            return <g key={edge.id} className={`seq-neighborhood-link ${edge.type} ${active ? 'is-active' : ''} ${selectedEdgeId === edge.id ? 'is-selected' : ''}`}
              role="button" tabIndex={0} aria-label={edgeSentence(edge, byId)}
              onClick={() => setSelectedEdgeId(edge.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdgeId(edge.id) } }}>
              <path d={`M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${(a.y + b.y) / 2 - Math.min(45, Math.abs(a.x - b.x) / 7)} ${b.x} ${b.y}`} className="seq-neighborhood-visible-line" />
              <path d={`M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${(a.y + b.y) / 2 - Math.min(45, Math.abs(a.x - b.x) / 7)} ${b.x} ${b.y}`} className="seq-neighborhood-hit-line" />
            </g>
          })}
          {nodes.map(node => {
            const post = byId.get(node.id)
            if (!post) return null
            const isSelected = node.id === activeSelection
            const isFocus = node.id === seedId
            const related = isSelected || relevant.some(edge => edge.source === node.id || edge.target === node.id)
            return <g key={node.id} className={`seq-neighborhood-node ${isSelected ? 'is-selected' : ''} ${isFocus ? 'is-focus' : ''} ${related ? 'is-related' : ''}`}
              role="button" tabIndex={0} aria-label={`${post.author}: ${post.text.slice(0, 110)}`}
              onClick={() => choosePost(node.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choosePost(node.id) } }}>
              {isSelected && <circle cx={node.x} cy={node.y} r="17" className="seq-neighborhood-node-halo" filter="url(#seq-node-glow)" />}
              <circle cx={node.x} cy={node.y} r={nodeRadius(post, isSelected, isFocus)} className="seq-neighborhood-node-core" />
              {isSelected && <circle cx={node.x} cy={node.y} r="15" className="seq-neighborhood-node-ring" />}
              {(isSelected || isFocus) && <text x={node.x > 970 ? node.x - 19 : node.x + 19} y={node.y + 4}
                textAnchor={node.x > 970 ? 'end' : 'start'} className="seq-neighborhood-node-label">{post.author}</text>}
              <circle cx={node.x} cy={node.y} r="13" className="seq-neighborhood-node-hit" />
            </g>
          })}
        </svg> : <div className="seq-neighborhood-empty">Posts appear here as the investigation streams in.</div>}
        <div className="seq-neighborhood-map-bottom"><p><span className="seq-neighborhood-key reply" /> Reply <span className="seq-neighborhood-key quote" /> Quote {semantic.length > 0 && <><span className="seq-neighborhood-key semantic" /> Shared wording</>}</p>
          <div><button type="button" onClick={() => setZoom(value => Math.max(1, +(value / 1.3).toFixed(2)))} disabled={zoom <= 1} aria-label="Zoom out"><Minus size={16} /></button>
            <button type="button" onClick={() => { setZoom(1); setFocusId(seedId) }} aria-label="Fit graph"><Focus size={16} /></button>
            <button type="button" onClick={() => setZoom(value => Math.min(2.7, +(value * 1.3).toFixed(2)))} disabled={zoom >= 2.7} aria-label="Zoom in"><Plus size={16} /></button></div>
        </div>
      </div>
      <aside className="seq-neighborhood-inspector" aria-label="Selected post and connections">
        <label className="seq-neighborhood-search"><Search size={15} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Find a post or author" aria-label="Find a post or author" />
          {search && <button type="button" onClick={() => setSearch('')} aria-label="Clear search"><X size={14} /></button>}</label>
        {search && <div className="seq-neighborhood-results" aria-label="Search results">{matches.length ? matches.map(post => <button key={post.id} type="button" onClick={() => choosePost(post.id, true)}><strong>{post.author}</strong><span>{post.text.slice(0, 92)}</span></button>) : <p>No captured post matches this search.</p>}</div>}
        {selected ? <>
          {selectedEdge ? <div className="seq-neighborhood-proof"><div className="seq-neighborhood-proof-title"><Link2 size={15} /><strong>{selectedEdge.type === 'reply' ? 'Recorded reply' : selectedEdge.type === 'quote' ? 'Recorded quote' : 'Measured similarity'}</strong><button type="button" onClick={() => setSelectedEdgeId(null)} aria-label="Close edge explanation"><X size={14} /></button></div><p>{edgeSentence(selectedEdge, byId)}</p>
            <div className="seq-neighborhood-proof-posts"><button type="button" onClick={() => setSelectedId(selectedEdge.source)}>Inspect {byId.get(selectedEdge.source)?.author || 'source post'}</button><button type="button" onClick={() => setSelectedId(selectedEdge.target)}>Inspect {byId.get(selectedEdge.target)?.author || 'referenced post'}</button></div>
            {selectedEdge.type === 'semantic' && <small>Similarity is a navigation signal; it does not show agreement, copying, or influence.</small>}</div> : null}
          <div className="seq-neighborhood-person"><div className="seq-neighborhood-avatar"><span>{initials(selected)}</span>{selected.avatar && <img src={selected.avatar} alt="" onError={event => { event.currentTarget.style.display = 'none' }} />}</div><div><strong>{selected.author}</strong>{selected.handle && <span>@{selected.handle}</span>}</div></div>
          <time dateTime={selected.publishedAt}>{localTime(selected.publishedAt)}</time>
          {annotations[selected.id] && <div className="seq-neighborhood-role"><strong>{annotations[selected.id].role}</strong>{annotations[selected.id].focus && <span>{annotations[selected.id].focus}</span>}</div>}
          <p className="seq-neighborhood-text">{selected.text}</p>
          {selected.textIsExcerpt && <p className="seq-neighborhood-excerpt">Captured excerpt; the original may contain more text.</p>}
          <div className="seq-neighborhood-post-actions"><button type="button" onClick={() => onOpenPost(selected)}>Open post context <ArrowUpRight size={14} /></button>
            {selected.url && <a href={selected.url} target="_blank" rel="noopener noreferrer">View on X <ArrowUpRight size={14} /></a>}</div>
          <div className="seq-neighborhood-relations">
            {([['Earlier references', earlier], ['Later responses', later], ['Shared wording', similar]] as const).map(([title, edges]) => <div className="seq-neighborhood-relation-group" key={title}>
              <h4>{title} <span>{edges.length}</span></h4>
              {edges.length ? edges.slice(0, 4).map(edge => {
                const other = byId.get(edge.source === selected.id ? edge.target : edge.source)
                return <button key={edge.id} type="button" onClick={() => { setSelectedEdgeId(edge.id); if (other) setSelectedId(other.id) }}><span className={`seq-neighborhood-key ${edge.type}`} /><span>{other?.author || 'Post'} <small>{edge.type === 'semantic' ? 'similar wording' : edge.type}</small></span><ArrowUpRight size={13} /></button>
              }) : <p>No captured {title.toLowerCase()} in this view.</p>}
              {edges.length > 4 && <small>{edges.length - 4} more links on the map.</small>}
            </div>)}
          </div>
          <button className="seq-neighborhood-center" type="button" onClick={() => { setFocusId(selected.id); setZoom(value => Math.max(value, 1.7)); setSelectedEdgeId(null) }}><Focus size={14} /> Focus on this post</button>
        </> : <p className="seq-neighborhood-empty-side">Select a post to inspect its connections.</p>}
      </aside>
    </div>
    <div className="seq-neighborhood-foot"><span>{mappedPosts.length} mapped from {dayPosts.length} captured · {represented.size} with visible links</span>
      <span>Rows are {modelLabel ? `suggested by Baseten ${modelLabel}` : 'visual groupings'}; solid links are recorded X references, dashed links compare wording. Direct seed links are revealed when inspected.</span>
      <span>Shared wording and timing do not prove copying, influence, or the original source.</span></div>
  </section>
}
