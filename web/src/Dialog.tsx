import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { BookOpen, ExternalLink, X } from 'lucide-react'
import { tweetLink, verdictLabels } from './evidence'
import type { Evidence } from './investigation-state'

export default function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => { ref.current?.showModal() }, [])
  return <dialog ref={ref} className="modal" aria-labelledby={titleId} onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <div className="modal-heading"><h2 id={titleId}>{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20} /></button></div>
    {children}
  </dialog>
}

export function EvidenceDialog({ item, onClose }: { item: Evidence; onClose: () => void }) {
  const link = tweetLink(item)
  return <Dialog title={item.author} onClose={onClose}>
    <span className={`post-relation relation-${item.verdict ?? 'pending'}`}>{item.verdict ? verdictLabels[item.verdict] : item.capture ? item.context ?? 'Saved source' : 'Not evaluated'}</span><blockquote className="inspect-quote"><a href={link.href} target="_blank" rel="noopener noreferrer">{item.text}</a></blockquote>
    <div className="inspect-explanation"><span className="eyebrow">WHY THIS DISTINCTION MATTERS</span><p>{item.explanation ?? 'No semantic explanation has been received for this post.'}</p></div><div className="fixture-reference"><BookOpen size={14} />{item.labelSource === 'editorial' ? 'Editorial note · not model-scored' : item.labelSource === 'fixture' ? 'Hand-labelled fixture' : item.labelSource === 'model' ? 'Model evaluation' : 'Source reference'} <code>{item.id}</code></div>
    {item.capture && <div className="capture-details">
      {item.capture.textIsExcerpt && <p><strong>Truncated X embed excerpt.</strong> The captured text stops where the endpoint stopped. The missing text has not been reconstructed.</p>}
      <p><strong>Published:</strong> <time dateTime={item.publishedAt}>{item.publishedAt}</time></p>
      <p><strong>Captured:</strong> <time dateTime={item.capture.capturedAt}>{item.capture.capturedAt}</time></p>
      <p><strong>Source:</strong> {item.capture.method}</p>
      {item.quotedPostId && <p><strong>Quoted post:</strong> <a href={`https://x.com/i/status/${item.quotedPostId}`} target="_blank" rel="noopener noreferrer">{item.quotedPostId}</a></p>}
      <details><summary>Capture integrity</summary><p>Author ID: <code>{item.authorId ?? 'Not supplied'}</code></p><p>Raw payload SHA-256: <code>{item.capture.sha256}</code></p></details>
    </div>}
    <a className="primary-button source-link" href={link.href} target="_blank" rel="noopener noreferrer">{link.label}<ExternalLink size={14} /></a>
    <p className="modal-small">{link.direct ? 'This is a supplied post reference, not a live availability check.' : 'No post ID was supplied. This link searches its wording on X; it is not an exact post link.'}</p>
  </Dialog>
}
