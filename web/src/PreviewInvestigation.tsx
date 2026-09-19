import { useMemo } from 'react'
import type { Demo } from './demo'
import { createDemoPlayback } from './demo-events'
import { createFrontierRecording } from './frontier-recording'
import { useEventPlayback } from './useEventPlayback'
import type { InvestigationState } from './investigation-state'
import Investigation from './Investigation'

// This boundary selects either illustrative fixtures or the saved source
// snapshot. Neither is presented as a live or recorded production pipeline run.
export default function PreviewInvestigation({ demo, runId, onBack, onExport, onAbout }: {
  demo: Demo; runId: string; onBack: () => void; onExport: (state: InvestigationState) => void; onAbout: () => void
}) {
  const source = useMemo(() => demo.sourceType === 'snapshot' ? createFrontierRecording(runId) : createDemoPlayback(demo, runId), [demo, runId])
  const { state, controls, generation } = useEventPlayback(source)
  return <Investigation key={generation} state={state} playback={controls} onBack={onBack} onExport={onExport} onAbout={onAbout} />
}
