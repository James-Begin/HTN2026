import { useMemo, useState } from 'react'
import { ArrowUpRight, Focus, Link2, MessageCircle, Minus, Plus, Search, X } from 'lucide-react'
import {
  buildObservedEdges, buildSemanticEdges, connectedComponent, layoutNeighborhood,
  type GraphEdge, type GraphPost, type SemanticEdge,
} from './graphData'
import './neighborhood.css'

export type NeighborhoodProps = {
  posts: GraphPost[]
  seedId: string
  semanticEdges?: SemanticEdge[]
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
  return `${source} and ${target} have a measured text similarity of ${edge.cosine?.toFixed(3)} (${edge.model}). This suggests related wording or topic, not agreement or influence.`
}

export default function Neighborhood({ posts, seedId, semanticEdges = [], onOpenPost }: NeighborhoodProps) {
  const [layer, setLayer] = useState<Layer>('all')
  const [throughDay, setThroughDay] = useState('all')
  const [focusId, setFocusId] = useState(seedId)
  const [selectedId, setSelectedId] = useState(seedId)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [zoom, setZoom] = useState(1)

  const allPosts = useMemo(() => [...new Map(posts.map(post => [post.id, post])).values()], [posts])
  const days = useMemo(() => [...new Set(allPosts.map(post => easternDay(post.publishedAt)).filter(Boolean))].sort(), [allPosts])
  const dayPosts = useMemo(() => throughDay === 'all' ? allPosts
    : allPosts.filter(post => easternDay(post.publishedAt) <= throughDay), [allPosts, throughDay])
  const byId = useMemo(() => new Map(dayPosts.map(post => [post.id, post])), [dayPosts])
  const observed = useMemo(() => buildObservedEdges(dayPosts), [dayPosts])
  const semantic = useMemo(() => buildSemanticEdges(dayPosts, semanticEdges), [dayPosts, semanticEdges])
  const shownEdges = useMemo(() => [...observed, ...semantic].filter(edge => layer === 'all' || edge.type === layer), [observed, semantic, layer])
  const activeFocus = byId.has(focusId) ? focusId : byId.has(seedId) ? seedId : dayPosts[0]?.id
  const activeSelection = byId.has(selectedId) ? selectedId : activeFocus
  const componentIds = useMemo(() => activeFocus ? new Set(connectedComponent(activeFocus, shownEdges)) : new Set<string>(), [activeFocus, shownEdges])
  const componentEdges = useMemo(() => shownEdges.filter(edge => componentIds.has(edge.source) && componentIds.has(edge.target)), [shownEdges, componentIds])
  const nodes = useMemo(() => activeFocus ? layoutNeighborhood(activeFocus, componentEdges, dayPosts) : [], [activeFocus, componentEdges, dayPosts])
  const selected = activeSelection ? byId.get(activeSelection) : undefined
  const selectedEdge = selectedEdgeId ? componentEdges.find(edge => edge.id === selectedEdgeId) : undefined
  const relevant = useMemo(() => activeSelection ? componentEdges.filter(edge => edge.source === activeSelection || edge.target === activeSelection) : [], [activeSelection, componentEdges])
  const matches = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return []
    return dayPosts.filter(post => `${post.author} ${post.handle || ''} ${post.text}`.toLowerCase().includes(query))
      .sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 8)
  }, [dayPosts, search])
  const represented = new Set(observed.flatMap(edge => [edge.source, edge.target]))
  const viewWidth = 1000 / zoom
  const viewHeight = 640 / zoom
  const viewX = 500 - viewWidth / 2
  const viewY = 320 - viewHeight / 2

  function choosePost(id: string, center = false) {
    setSelectedId(id)
    setSelectedEdgeId(null)
    if (center || !componentIds.has(id)) setFocusId(id)
    setSearch('')
  }

  return <section className="seq-neighborhood" aria-label="Conversation neighborhood">
    <div className="seq-neighborhood-head">
      <div><h2>Conversation neighborhood</h2><p>Observed replies and quotes inside this retrieved sample. Select any connection to see its source.</p></div>
      <div className="seq-neighborhood-stats"><strong>{observed.length}</strong><span>recorded links</span><strong>{dayPosts.length}</strong><span>captured posts</span></div>
    </div>
    <div className="seq-neighborhood-controls">
      <div className="seq-neighborhood-layers" role="group" aria-label="Connection type">
        {([['all', 'All links'], ['reply', 'Replies'], ['quote', 'Quotes'], ['semantic', 'Similar text']] as const).map(([value, label]) =>
          <button key={value} type="button" aria-pressed={layer === value} className={layer === value ? 'active' : ''}
            disabled={value === 'semantic' && semantic.length === 0}
            title={value === 'semantic' && semantic.length === 0 ? 'Similarity appears when embeddings are available' : undefined}
            onClick={() => { setLayer(value); setSelectedEdgeId(null) }}>{label}</button>)}
      </div>
      <label className="seq-neighborhood-date"><span>Through</span><select value={throughDay} onChange={event => { setThroughDay(event.target.value); setSelectedEdgeId(null) }}>
        <option value="all">All captured days</option>{days.map(day => <option key={day} value={day}>{shortDay(day)} ET</option>)}
      </select></label>
    </div>
    <div className="seq-neighborhood-workspace">
      <div className="seq-neighborhood-map">
        <div className="seq-neighborhood-map-top"><span><span className="seq-neighborhood-live-dot" /> {activeFocus === seedId ? 'Around Dario’s post' : `Around ${byId.get(activeFocus)?.author || 'selected post'}`}</span>
          {activeFocus !== seedId && byId.has(seedId) && <button type="button" onClick={() => choosePost(seedId, true)}>Back to Dario</button>}
        </div>
        {activeFocus ? <svg className="seq-neighborhood-svg" viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`} role="img" aria-label={`Graph of ${nodes.length} posts connected by ${componentEdges.length} recorded links`}>
          <defs><filter id="seq-node-glow"><feGaussianBlur stdDeviation="5" /></filter></defs>
          {componentEdges.map(edge => {
            const a = nodes.find(node => node.id === edge.source)
            const b = nodes.find(node => node.id === edge.target)
            if (!a || !b) return null
            const active = selectedEdgeId === edge.id || (!!activeSelection && (edge.source === activeSelection || edge.target === activeSelection))
            return <g key={edge.id} className={`seq-neighborhood-link ${edge.type} ${active ? 'is-active' : ''} ${selectedEdgeId === edge.id ? 'is-selected' : ''}`}
              role="button" tabIndex={0} aria-label={edgeSentence(edge, byId)}
              onClick={() => setSelectedEdgeId(edge.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdgeId(edge.id) } }}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="seq-neighborhood-visible-line" />
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="seq-neighborhood-hit-line" />
            </g>
          })}
          {nodes.map(node => {
            const post = byId.get(node.id)
            if (!post) return null
            const isSelected = node.id === activeSelection
            const isFocus = node.id === activeFocus
            const related = isSelected || relevant.some(edge => edge.source === node.id || edge.target === node.id)
            return <g key={node.id} className={`seq-neighborhood-node ${isSelected ? 'is-selected' : ''} ${isFocus ? 'is-focus' : ''} ${related ? 'is-related' : ''}`}
              role="button" tabIndex={0} aria-label={`${post.author}: ${post.text.slice(0, 110)}`}
              onClick={() => choosePost(node.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choosePost(node.id) } }}>
              {isSelected && <circle cx={node.x} cy={node.y} r="17" className="seq-neighborhood-node-halo" filter="url(#seq-node-glow)" />}
              <circle cx={node.x} cy={node.y} r={nodeRadius(post, isSelected, isFocus)} className="seq-neighborhood-node-core" />
              {isSelected && <circle cx={node.x} cy={node.y} r="15" className="seq-neighborhood-node-ring" />}
              {(isSelected || isFocus) && <text x={node.x > 790 ? node.x - 19 : node.x + 19} y={node.y + 4}
                textAnchor={node.x > 790 ? 'end' : 'start'} className="seq-neighborhood-node-label">{post.author}</text>}
              <circle cx={node.x} cy={node.y} r="13" className="seq-neighborhood-node-hit" />
            </g>
          })}
        </svg> : <div className="seq-neighborhood-empty">Posts appear here as the investigation streams in.</div>}
        <div className="seq-neighborhood-map-bottom"><p><span className="seq-neighborhood-key reply" /> Reply <span className="seq-neighborhood-key quote" /> Quote {semantic.length > 0 && <><span className="seq-neighborhood-key semantic" /> Similar text</>}</p>
          <div><button type="button" onClick={() => setZoom(value => Math.max(1, +(value / 1.3).toFixed(2)))} disabled={zoom <= 1} aria-label="Zoom out"><Minus size={16} /></button>
            <button type="button" onClick={() => setZoom(1)} aria-label="Fit graph"><Focus size={16} /></button>
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
          <p className="seq-neighborhood-text">{selected.text}</p>
          {selected.textIsExcerpt && <p className="seq-neighborhood-excerpt">Captured excerpt; the original may contain more text.</p>}
          <div className="seq-neighborhood-post-actions"><button type="button" onClick={() => onOpenPost(selected)}>Open post context <ArrowUpRight size={14} /></button>
            {selected.url && <a href={selected.url} target="_blank" rel="noopener noreferrer">View on X <ArrowUpRight size={14} /></a>}</div>
          <div className="seq-neighborhood-relations"><div className="seq-neighborhood-relations-head"><MessageCircle size={14} /><strong>{relevant.length} visible connection{relevant.length === 1 ? '' : 's'}</strong></div>
            {relevant.length ? relevant.slice(0, 7).map(edge => {
              const other = byId.get(edge.source === selected.id ? edge.target : edge.source)
              return <button key={edge.id} type="button" onClick={() => { setSelectedEdgeId(edge.id); if (other) setSelectedId(other.id) }}><span className={`seq-neighborhood-key ${edge.type}`} /><span>{edge.type === 'reply' ? 'Reply' : edge.type === 'quote' ? 'Quote' : 'Similar text'} · {other?.author || 'Post'}</span><ArrowUpRight size={13} /></button>
            }) : <p>No captured link joins this post to the current view.</p>}
            {relevant.length > 7 && <small>{relevant.length - 7} more links; select them on the map.</small>}
          </div>
          {activeFocus !== selected.id && <button className="seq-neighborhood-center" type="button" onClick={() => { setFocusId(selected.id); setSelectedEdgeId(null) }}><Focus size={14} /> Center on this post</button>}
        </> : <p className="seq-neighborhood-empty-side">Select a post to inspect its connections.</p>}
      </aside>
    </div>
    <div className="seq-neighborhood-foot"><span>{componentIds.size} post{componentIds.size === 1 ? '' : 's'} in this view · {represented.size} with a captured relationship across the sample</span>
      <span>{dayPosts.length - represented.size} posts have no captured relationship. Search can still open them.</span>
      {semantic.length === 0 && <span>Text similarity and personas will appear when those fields are measured; neither is inferred here.</span>}
      <span>Position is for navigation; distance on this map is not a similarity score.</span></div>
  </section>
}
