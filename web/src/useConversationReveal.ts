import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/** The smallest contract the reveal scheduler needs from an investigation post. */
export type RevealablePost = { id: string }

export type ConversationRevealPhase = 'idle' | 'revealing' | 'complete'

export type ConversationRevealState<TPost extends RevealablePost> = {
  /** Posts in their original arrival order that have been released to the UI. */
  presentedPosts: TPost[]
  /** Useful when a graph stores post data independently from the lineage list. */
  presentedIds: readonly string[]
  /** `revealing` begins with a deliberate, readable first few arrivals. */
  phase: ConversationRevealPhase
  /** Number of known posts that are waiting to enter the graph and lineage. */
  pendingCount: number
  /** Number of distinct posts received for this run. */
  totalCount: number
  /** True after the current queue has been fully presented. */
  isComplete: boolean
  /** Finish the currently known queue immediately. New arrivals can still stream in. */
  skip: () => void
  /** Start the known posts from the beginning using the same deterministic pacing. */
  reset: () => void
}

const FIRST_POST_DELAY_MS = 260
const SLOW_REVEAL_COUNT = 7
const SLOW_REVEAL_DELAY_MS = 760
const FASTEST_REVEAL_DELAY_MS = 165

function delayForReveal(revealedCount: number, backlogCount: number) {
  if (revealedCount === 0) return FIRST_POST_DELAY_MS
  if (revealedCount < SLOW_REVEAL_COUNT) return SLOW_REVEAL_DELAY_MS

  // The queue becomes more energetic as evidence accumulates, while preserving
  // enough time for the graph and lineage to read as one shared arrival.
  const acceleration = Math.min(155, (revealedCount - SLOW_REVEAL_COUNT) * 12)
  const backlogPressure = Math.min(65, Math.max(0, backlogCount - 8) * 3)
  return Math.max(FASTEST_REVEAL_DELAY_MS, 410 - acceleration - backlogPressure)
}

/**
 * Turns an append-heavy post stream into a single, deterministic presentation
 * queue. It owns no selection, scroll position, or layout state, so graph and
 * lineage components can share it without taking control away from the reader.
 */
export function useConversationReveal<TPost extends RevealablePost>(posts: readonly TPost[]): ConversationRevealState<TPost> {
  const knownPosts = useRef(new Map<string, TPost>())
  const knownOrder = useRef<string[]>([])
  const queuedIds = useRef<string[]>([])
  const presentedIdSet = useRef(new Set<string>())
  const presentedOrder = useRef<string[]>([])
  const revealedCount = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  const generation = useRef(0)
  const schedule = useRef<() => void>(() => undefined)

  const [presentedIds, setPresentedIds] = useState<string[]>([])
  const [postVersion, setPostVersion] = useState(0)
  const [totalCount, setTotalCount] = useState(0)
  const [phase, setPhase] = useState<ConversationRevealPhase>('idle')
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)

  const clearTimer = useCallback(() => {
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current)
      timer.current = undefined
    }
    generation.current += 1
  }, [])

  const publishPresented = useCallback(() => {
    setPresentedIds([...presentedOrder.current])
  }, [])

  const scheduleNext = useCallback(() => {
    if (timer.current !== undefined) return
    if (queuedIds.current.length === 0) {
      setPhase(presentedOrder.current.length === 0 ? 'idle' : 'complete')
      return
    }

    setPhase('revealing')
    const run = generation.current
    const delay = delayForReveal(revealedCount.current, queuedIds.current.length)
    timer.current = window.setTimeout(() => {
      timer.current = undefined
      if (run !== generation.current) return

      const id = queuedIds.current.shift()
      if (id && !presentedIdSet.current.has(id)) {
        presentedIdSet.current.add(id)
        presentedOrder.current.push(id)
        revealedCount.current += 1
        publishPresented()
      }
      schedule.current()
    }, delay)
  }, [publishPresented])

  schedule.current = scheduleNext

  const skip = useCallback(() => {
    clearTimer()
    let didPresent = false
    for (const id of queuedIds.current.splice(0)) {
      if (presentedIdSet.current.has(id)) continue
      presentedIdSet.current.add(id)
      presentedOrder.current.push(id)
      revealedCount.current += 1
      didPresent = true
    }
    if (didPresent) publishPresented()
    setPhase(presentedOrder.current.length === 0 ? 'idle' : 'complete')
  }, [clearTimer, publishPresented])

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    let added = false
    let changed = false
    for (const post of posts) {
      const id = post.id.trim()
      if (!id) continue

      const existing = knownPosts.current.get(id)
      if (existing !== post) {
        knownPosts.current.set(id, post)
        changed = true
      }
      if (!existing) {
        knownOrder.current.push(id)
        if (!presentedIdSet.current.has(id)) queuedIds.current.push(id)
        added = true
      }
    }

    if (added) setTotalCount(knownOrder.current.length)
    if (changed) setPostVersion(version => version + 1)
    if (queuedIds.current.length > 0) {
      if (reducedMotion) skip()
      else schedule.current()
    }
  }, [posts, reducedMotion, skip])

  useEffect(() => () => clearTimer(), [clearTimer])

  const reset = useCallback(() => {
    clearTimer()
    queuedIds.current = [...knownOrder.current]
    presentedIdSet.current.clear()
    presentedOrder.current = []
    revealedCount.current = 0
    publishPresented()
    setPhase(queuedIds.current.length === 0 ? 'idle' : 'revealing')
    if (reducedMotion) skip()
    else schedule.current()
  }, [clearTimer, publishPresented, reducedMotion, skip])

  const presentedPosts = useMemo(
    () => presentedIds.flatMap(id => {
      const post = knownPosts.current.get(id)
      return post ? [post] : []
    }),
    [postVersion, presentedIds],
  )

  return {
    presentedPosts,
    presentedIds,
    phase,
    pendingCount: totalCount - presentedIds.length,
    totalCount,
    isComplete: phase === 'complete',
    skip,
    reset,
  }
}
