import type { Evidence, Verdict } from './investigation-state'

export const verdictLabels: Record<Verdict, string> = {
  same: 'Same assertion', uncertain: 'Uncertain match', different: 'Different assertion', meta: 'Commentary / denial',
}

// Fixture identities are not post IDs. Only a supplied X URL or explicit numeric
// postId gets a permalink; absent IDs get an honestly labelled text search.
export function tweetLink(item: Evidence) {
  let href: string | undefined
  if (item.url) {
    try {
      const url = new URL(item.url)
      if (url.protocol === 'https:' && ['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(url.hostname) && /^\/(?:i|[\w]+)\/status\/\d+\/?$/.test(url.pathname)) href = url.href
    } catch { /* Invalid source URLs use the same search fallback as missing IDs. */ }
  }
  if (!href && item.postId && /^\d+$/.test(item.postId)) href = `https://x.com/i/status/${item.postId}`
  return href
    ? { href, label: 'Open post on X', direct: true }
    : { href: `https://x.com/search?${new URLSearchParams({ q: `"${item.text}"`, src: 'typed_query', f: 'live' })}`, label: 'Search text on X', direct: false }
}
