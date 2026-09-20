import { useCallback, useEffect, useRef, useState } from 'react'
import { mergeBucket, mergePosts, normalizePost, normalizeRun, record, validateEvent } from './stream'
import type { Bucket, Post, Run, RunMode, RunStatus, StreamEvent } from './types'

type StartedRun = { runId: string; eventsUrl: string; error?: string }
type Milestones = { started: boolean; seedResolved: boolean; planReady: boolean; runReady: boolean }

export type InvestigationRunState = {
  run: Run | null
  posts: Post[]
  seedPost: Post | null
  status: RunStatus
  error: string
  busy: boolean
  activity: string
  lastEventType: string
  sequence: number
  mode: RunMode | null
  milestones: Milestones
}

const initialMilestones = (): Milestones => ({ started: false, seedResolved: false, planReady: false, runReady: false })

export function useInvestigationRun() {
  const [state, setState] = useState<InvestigationRunState>({
    run: null, posts: [], seedPost: null, status: 'idle', error: '', busy: false,
    activity: '', lastEventType: '', sequence: 0, mode: null, milestones: initialMilestones(),
  })
  const generation = useRef(0)
  const streamRef = useRef<EventSource | null>(null)
  const runIdRef = useRef<string | null>(null)
  const sequenceRef = useRef(0)

  const cancelJob = useCallback((id: string) => {
    fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }).catch(() => {})
  }, [])

  const close = useCallback((cancel: boolean) => {
    streamRef.current?.close()
    streamRef.current = null
    if (cancel && runIdRef.current) cancelJob(runIdRef.current)
    runIdRef.current = null
  }, [cancelJob])

  const stop = useCallback(() => {
    generation.current += 1
    close(true)
    setState(previous => previous.status === 'running' || previous.status === 'reconnecting'
      ? { ...previous, status: 'stopped', busy: false, activity: '', lastEventType: 'run.stopped' }
      : previous)
  }, [close])

  useEffect(() => () => {
    generation.current += 1
    close(true)
  }, [close])

  const start = useCallback(async ({ seed, mode }: { seed: string; mode: RunMode }) => {
    const id = ++generation.current
    close(true)
    sequenceRef.current = 0
    setState({
      run: null, posts: [], seedPost: null, status: 'running', error: '', busy: true,
      activity: 'Starting the investigation…', lastEventType: '', sequence: 0, mode,
      milestones: initialMilestones(),
    })
    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seed, mode }),
      })
      const data = await response.json() as StartedRun
      if (!response.ok) throw new Error(data.error || 'Investigation failed')
      if (typeof data.runId !== 'string' || typeof data.eventsUrl !== 'string') throw new Error('Invalid investigation response')
      if (id !== generation.current) {
        cancelJob(data.runId)
        return false
      }
      runIdRef.current = data.runId
      const stream = new EventSource(data.eventsUrl)
      let terminal = false
      streamRef.current = stream
      stream.addEventListener('sequitor', raw => {
        if (id !== generation.current || terminal) return
        try {
          const decoded: unknown = JSON.parse((raw as MessageEvent).data)
          if (!record(decoded) || decoded.runId !== data.runId || !Number.isInteger(decoded.sequence)
            || Number(decoded.sequence) < 1 || typeof decoded.type !== 'string' || !record(decoded.payload)) {
            throw new Error('Invalid investigation event')
          }
          const message = decoded as unknown as StreamEvent
          if (message.sequence <= sequenceRef.current) return
          validateEvent(message)
          sequenceRef.current = message.sequence
          setState(previous => {
            const payload = message.payload
            let run = previous.run
            let posts = previous.posts
            let seedPost = previous.seedPost
            let status: RunStatus = 'running'
            let error = previous.error
            let activity = previous.activity
            const milestones = { ...previous.milestones }
            if (message.type === 'run.started') milestones.started = true
            if (message.type === 'stage') activity = String(payload.name)
            if (message.type === 'seed.resolved') {
              milestones.seedResolved = true
              seedPost = payload.post
                ? normalizePost(payload.post as Post)
                : normalizePost({ id: 'seed-text', sourceType: 'input', author: 'Search input', publishedAt: '', text: String(payload.text) })
              const entryPost = payload.entryPost ? normalizePost(payload.entryPost as Post) : null
              posts = mergePosts(posts, [seedPost, ...entryPost ? [entryPost] : []])
              if (run) run = { ...run, title: String(payload.text).split('\n')[0].slice(0, 110), seedPost, posts }
            }
            if (message.type === 'plan.ready' || message.type === 'context.expanded') {
              if (message.type === 'plan.ready') milestones.planReady = true
              if (run) run = { ...run, searchPlan: payload.plan as Run['searchPlan'] }
            }
            if (message.type === 'run.ready') {
              milestones.runReady = true
              run = normalizeRun(payload as unknown as Run)
              posts = run.posts
              seedPost = run.seedPost || seedPost
              if (seedPost && !run.seedPost) run = { ...run, seedPost }
              activity = run.streamSource === 'cache' ? 'Loading cached results…' : 'Retrieving posts…'
            }
            if (message.type === 'posts.upsert') {
              posts = mergePosts(posts, payload.posts as Post[])
              if (run) run = { ...run, posts }
            }
            if (message.type === 'buckets.upsert' && run) {
              run = { ...run, buckets: mergeBucket(run.buckets, payload.bucket as Bucket) }
            }
            if (message.type === 'model.ready' && run) {
              run = { ...run, model: { ...run.model, baseten: payload.model as NonNullable<Run['model']>['baseten'] } }
            }
            if (message.type === 'run.completed') {
              status = 'completed'
              activity = ''
              if (run) run = { ...run, model: payload.model as Run['model'] || run.model,
                rankingCoverage: String(payload.rankingCoverage || run.rankingCoverage),
                xSpend: typeof payload.xSpend === 'number' ? payload.xSpend : run.xSpend }
            }
            if (message.type === 'run.failed' || message.type === 'run.stopped') {
              status = message.type === 'run.failed' ? 'failed' : 'stopped'
              activity = ''
              if (message.type === 'run.failed') error = String(payload.message || 'Investigation failed')
            }
            return {
              run, posts, seedPost, status, error, activity,
              busy: status === 'running',
              lastEventType: message.type, sequence: message.sequence, mode: previous.mode, milestones,
            }
          })
          if (message.type === 'run.completed' || message.type === 'run.failed' || message.type === 'run.stopped') {
            terminal = true
            stream.close()
            streamRef.current = null
            runIdRef.current = null
          }
        } catch (cause) {
          terminal = true
          close(true)
          setState(previous => ({ ...previous, status: 'failed', busy: false, activity: '',
            error: cause instanceof Error ? cause.message : 'Invalid investigation event' }))
        }
      })
      stream.onerror = () => {
        if (id !== generation.current || terminal) return
        if (stream.readyState === EventSource.CLOSED) {
          terminal = true
          close(true)
          setState(previous => ({ ...previous, status: 'failed', busy: false, activity: '',
            error: 'Investigation stream closed; partial results retained' }))
        } else {
          setState(previous => ({ ...previous, status: 'reconnecting', busy: true,
            activity: 'Reconnecting to the investigation…' }))
        }
      }
      return true
    } catch (cause) {
      if (id !== generation.current) return false
      close(true)
      setState(previous => ({ ...previous, status: 'failed', busy: false, activity: '',
        error: cause instanceof Error ? cause.message : 'Investigation failed' }))
      return false
    }
  }, [cancelJob, close])

  return { ...state, start, stop }
}
