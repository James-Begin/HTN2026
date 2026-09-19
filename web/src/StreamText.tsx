import { memo, useEffect, useMemo, useRef, useState } from 'react'

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return reduced
}

// This buffer only reveals RECEIVED text. It has no access to fixture summaries,
// event schedules, or future network chunks. Whole received words reserve width;
// new words necessarily extend the layout as additional text arrives.
const StreamText = memo(function StreamText({ text, paused, finished }: { text: string; paused: boolean; finished: boolean }) {
  const reduced = useReducedMotion()
  const [shown, setShown] = useState(0)
  const cursor = useRef(0)
  const immediate = reduced || finished
  const { words, length } = useMemo(() => {
    let offset = 0
    const words = text.split(/(\s+)/).map(part => {
      const start = offset
      const characters = Array.from(part)
      offset += characters.length
      return { part, characters, start }
    })
    return { words, length: offset }
  }, [text])

  useEffect(() => {
    if (immediate) { cursor.current = length; return }
    if (paused) return
    let frame = 0
    let previous = performance.now()
    let credit = 0
    const advance = (now: number) => {
      credit += Math.min(now - previous, 64)
      previous = now
      // Accelerate for large bursts rather than falling far behind the source.
      const perCharacter = length - cursor.current > 100 ? 6 : 24
      const count = Math.floor(credit / perCharacter)
      if (count) {
        credit -= count * perCharacter
        cursor.current = Math.min(length, cursor.current + count)
        setShown(cursor.current)
      }
      if (cursor.current < length) frame = requestAnimationFrame(advance)
    }
    if (cursor.current < length) frame = requestAnimationFrame(advance)
    return () => cancelAnimationFrame(frame)
  }, [length, paused, immediate])

  const count = immediate ? length : Math.min(length, Math.max(shown, cursor.current))
  return <div className="continuous-summary" data-visible-characters={count}>
    <p aria-hidden="true">{words.map(({ part, characters, start }, i) => /^\s+$/.test(part)
      ? part
      : <span className="stream-word" key={i}>{characters.map((character, j) => <span key={j} className={start + j < count ? 'stream-character shown' : 'stream-character'}>{character}</span>)}</span>)}</p>
    <p className="sr-only" role="status">{finished ? text : 'The explanation is streaming.'}</p>
  </div>
})
export default StreamText
