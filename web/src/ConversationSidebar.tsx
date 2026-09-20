import { ArrowUpRight, CornerUpLeft, Quote } from 'lucide-react'
import type { CSSProperties } from 'react'
import './conversation-sidebar.css'

/**
 * The small common shape used by the conversation view and live API payloads.
 * It intentionally mirrors GraphPost without coupling this presentational
 * component to the current graph implementation.
 */
export type ConversationSidebarPost = {
  id: string
  text: string
  publishedAt: string
  author: string
  handle?: string
  avatar?: string
  url?: string
  likes?: number | null
  parentId?: string | null
  quotedPostId?: string | null
}

export type ConversationSidebarContext = {
  title?: string
  entities?: string[]
}

export type ConversationSidebarStatus = 'waiting' | 'searching' | 'building' | 'complete' | 'error'

export type ConversationSidebarProps = {
  posts: ConversationSidebarPost[]
  selectedPost?: ConversationSidebarPost | null
  referenceId: string
  onSelect: (postId: string) => void
  context?: ConversationSidebarContext
  status?: ConversationSidebarStatus
}

type Relation = 'reply' | 'quote'
type LineageItem = { post: ConversationSidebarPost; relation?: Relation; direction: 'source' | 'ancestor' | 'descendant' }

const formatter = new Intl.DateTimeFormat('en-CA', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

function displayAuthor(post: ConversationSidebarPost) {
  return post.author.replace(/\s*·\s*@\S+$/, '') || post.handle || 'Unknown account'
}

function avatarLabel(post: ConversationSidebarPost) {
  return displayAuthor(post).replace(/^@/, '').slice(0, 2).toUpperCase() || '𝕏'
}

function xUrl(post: ConversationSidebarPost) {
  return post.url || `https://x.com/i/web/status/${post.id}`
}

function relationTo(post: ConversationSidebarPost, targetId: string): Relation | undefined {
  if (post.quotedPostId === targetId) return 'quote'
  if (post.parentId === targetId) return 'reply'
  return undefined
}

function lineageFor(source: ConversationSidebarPost, byId: Map<string, ConversationSidebarPost>) {
  const ancestors: LineageItem[] = []
  const visited = new Set([source.id])
  let current = source
  for (let step = 0; step < 4; step++) {
    const relation: Relation | undefined = current.quotedPostId ? 'quote' : current.parentId ? 'reply' : undefined
    const id = current.quotedPostId || current.parentId
    const parent = id ? byId.get(id) : undefined
    if (!parent || visited.has(parent.id)) break
    ancestors.unshift({ post: parent, relation, direction: 'ancestor' })
    visited.add(parent.id)
    current = parent
  }

  const descendants = [...byId.values()]
    .filter(post => post.id !== source.id && (post.parentId === source.id || post.quotedPostId === source.id))
    .sort((a, b) => Date.parse(a.publishedAt) - Date.parse(b.publishedAt) || a.id.localeCompare(b.id))
    .slice(0, 5)
    .map(post => ({ post, relation: relationTo(post, source.id), direction: 'descendant' as const }))

  return [...ancestors, ...descendants]
}

function relationLabel(relation: Relation | undefined, direction: LineageItem['direction']) {
  if (!relation) return 'Selected post'
  if (relation === 'quote') return direction === 'ancestor' ? 'Quoted source' : 'Quotes this post'
  return direction === 'ancestor' ? 'Parent post' : 'Replies to this post'
}

function TweetCard({ post, selected, reference, relation, relationDirection, onSelect, dense = false, revealOrder = 0 }: {
  post: ConversationSidebarPost
  selected?: boolean
  reference?: boolean
  relation?: Relation
  relationDirection?: LineageItem['direction']
  onSelect: (postId: string) => void
  dense?: boolean
  revealOrder?: number
}) {
  const author = displayAuthor(post)
  const date = Number.isNaN(Date.parse(post.publishedAt)) ? undefined : formatter.format(new Date(post.publishedAt))
  const style = { '--conversation-card-order': Math.min(revealOrder, 10) } as CSSProperties
  return <article className={`conversation-sidebar-card${selected ? ' is-selected' : ''}${dense ? ' is-dense' : ''}`} style={style}>
    <button className="conversation-sidebar-card-main" type="button" onClick={() => onSelect(post.id)} aria-pressed={selected}>
      <span className="conversation-sidebar-avatar" aria-hidden="true">
        <span>{avatarLabel(post)}</span>
        {post.avatar && <img src={post.avatar} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} />}
      </span>
      <span className="conversation-sidebar-card-copy">
        <span className="conversation-sidebar-author-row"><strong>{author}</strong>{post.handle && <span>@{post.handle.replace(/^@/, '')}</span>}</span>
        {date && <time dateTime={post.publishedAt}>{date}</time>}
      </span>
      {reference && <span className="conversation-sidebar-reference">Start</span>}
    </button>
    {(relation || selected) && <span className="conversation-sidebar-relation">{relation === 'quote' ? <Quote size={12} /> : relation === 'reply' ? <CornerUpLeft size={12} /> : null}{relationLabel(relation, relationDirection || 'source')}</span>}
    <button className="conversation-sidebar-text" type="button" onClick={() => onSelect(post.id)}>{post.text}</button>
    <a className="conversation-sidebar-open" href={xUrl(post)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${author}'s post on X`}>Open on X <ArrowUpRight size={13} /></a>
  </article>
}

function SidebarStatus({ status, count }: { status: ConversationSidebarStatus; count: number }) {
  const labels: Record<ConversationSidebarStatus, string> = {
    waiting: 'Ready to trace',
    searching: 'Finding posts',
    building: `${count} posts placed`,
    complete: `${count} posts captured`,
    error: 'Search paused',
  }
  return <p className={`conversation-sidebar-status is-${status}`} role="status"><span />{labels[status]}</p>
}

export default function ConversationSidebar({
  posts,
  selectedPost,
  referenceId,
  onSelect,
  context,
  status = 'waiting',
}: ConversationSidebarProps) {
  const byId = new Map(posts.map(post => [post.id, post]))
  const revealOrder = new Map(posts.map((post, index) => [post.id, index]))
  const reference = byId.get(referenceId)
  const source = selectedPost || reference || posts[0]
  const lineage = source ? lineageFor(source, byId) : []
  const lineageIds = new Set(lineage.map(item => item.post.id))
  const related = posts
    .filter(post => post.id !== source?.id && !lineageIds.has(post.id))
    .sort((a, b) => (b.likes || 0) - (a.likes || 0) || Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
    .slice(0, 10)

  return <aside className="conversation-sidebar" aria-label="Conversation details">
    {(context?.title || context?.entities?.length) && <section className="conversation-sidebar-context" aria-label="Conversation context">
      {context.title && <h2>{context.title}</h2>}
      {context.entities?.length ? <ul>{context.entities.slice(0, 5).map(entity => <li key={entity}>{entity}</li>)}</ul> : null}
    </section>}

    <SidebarStatus status={status} count={posts.length} />

    {source ? <section className="conversation-sidebar-selected" aria-label="Selected post">
      <div className="conversation-sidebar-heading"><h2>{source.id === referenceId ? 'Starting post' : 'Selected post'}</h2></div>
      <TweetCard post={source} selected reference={source.id === referenceId} onSelect={onSelect} revealOrder={revealOrder.get(source.id)} />
    </section> : <p className="conversation-sidebar-empty">Posts will appear here as the conversation is found.</p>}

    {lineage.length > 1 && <section className="conversation-sidebar-lineage" aria-label="Observed lineage">
      <div className="conversation-sidebar-heading"><h2>Lineage</h2><span>Observed links</span></div>
      <ol>{lineage.map(item => <li key={item.post.id} className={item.direction === 'source' ? 'is-source' : ''}>
        <span className="conversation-sidebar-line" />
        <TweetCard post={item.post} selected={item.post.id === source?.id} reference={item.post.id === referenceId} relation={item.relation} relationDirection={item.direction} onSelect={onSelect} dense revealOrder={revealOrder.get(item.post.id)} />
      </li>)}</ol>
    </section>}

    {related.length > 0 && <section className="conversation-sidebar-related" aria-label="Other captured posts">
      <div className="conversation-sidebar-heading"><h2>Captured posts</h2><span>{related.length}</span></div>
      <div>{related.map(post => <TweetCard key={post.id} post={post} selected={post.id === source?.id} reference={post.id === referenceId} onSelect={onSelect} dense revealOrder={revealOrder.get(post.id)} />)}</div>
    </section>}
  </aside>
}
