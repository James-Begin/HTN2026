import { useEffect, useReducer, useRef, useState } from 'react'
import { createInvestigationState, investigationReducer, isTerminal } from './investigation-state'
import type { InvestigationEvent, InvestigationState, PlaybackSource } from './investigation-state'

export type PlaybackControls = {
  playing: boolean
  toggle: () => void
  finish: () => void
  replay: () => void
}

type Action = { type: 'events'; events: InvestigationEvent[] } | { type: 'reset'; source: PlaybackSource }
const initialEvents = (source: PlaybackSource) => source.events.filter(entry => entry.at <= 0)
function initialState(source: PlaybackSource) {
  return initialEvents(source).reduce((state, entry) => investigationReducer(state, entry.event), createInvestigationState(source.info))
}
function reducePlayback(state: InvestigationState, action: Action): InvestigationState {
  return action.type === 'reset' ? initialState(action.source) : action.events.reduce(investigationReducer, state)
}

// A local ordered playback adapter, not a network transport. Its clock only
// delivers events. The UI receives state, never timestamps or fixture indexes.
// Remount the controller when changing sources (the App uses a per-run key).
export function useEventPlayback(source: PlaybackSource) {
  const [state, dispatch] = useReducer(reducePlayback, source, initialState)
  const [playing, setPlaying] = useState(true)
  const [generation, setGeneration] = useState(0)
  const position = useRef({ elapsed: 0, index: initialEvents(source).length })
  const complete = isTerminal(state.status)

  useEffect(() => {
    if (!playing || complete) return
    let frame = 0
    let previous = performance.now()
    const advance = (now: number) => {
      const cursor = position.current
      cursor.elapsed += Math.min(now - previous, 64)
      previous = now
      const events: InvestigationEvent[] = []
      while (cursor.index < source.events.length && source.events[cursor.index].at <= cursor.elapsed) {
        events.push(source.events[cursor.index++].event)
      }
      if (events.length) dispatch({ type: 'events', events })
      if (cursor.index < source.events.length) frame = requestAnimationFrame(advance)
    }
    frame = requestAnimationFrame(advance)
    return () => cancelAnimationFrame(frame)
  }, [source, playing, complete, generation])

  const controls: PlaybackControls = {
    playing: playing && !complete,
    toggle: () => setPlaying(value => !value),
    finish: () => {
      const events = source.events.slice(position.current.index).map(entry => entry.event)
      position.current.index = source.events.length
      dispatch({ type: 'events', events })
      setPlaying(false)
    },
    replay: () => {
      position.current = { elapsed: 0, index: initialEvents(source).length }
      dispatch({ type: 'reset', source })
      setGeneration(value => value + 1)
      setPlaying(true)
    },
  }
  return { state, controls, generation }
}
