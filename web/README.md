# Claimtrace visual prototype

A standalone React / TypeScript / Vite frontend. The Python pipeline and CLI are unchanged.

## Run locally

```bash
cd web
npm ci
npm run dev
```

Use the local URL printed by Vite. The development server binds to loopback, not the public network.

**External installation caveat:** the lockfile currently resolves packages through the original development environment's work registry mirror. Public npm was not reachable for verification during the initial repository upload, so pinned URLs, versions and integrity hashes were left unchanged. Before setting up outside that environment, verify the pinned artifacts against public npm and replace the mirror URLs with their public equivalents. Do not add work-registry credentials to this repository.

```bash
npm run build          # Type-check and build static assets
npm run preview        # Inspect the production build locally
npm run build:offline  # Build, then package a standalone HTML backup
```

## What works

- A minimal top navigation and responsive investigation workspace with three spaces: timeline, lineage, and key posts. Desktop columns scroll independently; smaller screens have section jump links.
- The first example replays captured X source posts for Dario Amodei's frontier essay. The other examples remain simulated.
- Interactive month/year counts: hover/focus, keyboard navigation, dated spotlighting, and year-to-month drilldown. The source snapshot counts only saved posts; other examples use illustrative volume.
- Event-driven investigations: a labelled local adapter emits started, activity, post, score, observation, explanation/token, and completion events into a pure reducer. No fixture indexes or elapsed-time thresholds in the columns.
- Frame-timed event delivery, soft evidence reveals, and character fades with stable received-word layout. Only received text is rendered; future fixture text is not preloaded into the view. Pause/resume, show-all, replay, and reduced-motion handling.
- Posts and observations update by stable ID without duplication; score events can precede post discovery. Open evidence dialogs follow the current post state.
- A data-driven timeline aggregates supplied monthly buckets. Missing counts stay unavailable; annual totals with incomplete coverage are labelled partial.
- Every displayed post opens X: a direct permalink when its ID was saved, otherwise an explicitly labelled text search. Source capture metadata, truncated-embed warnings, quote references, and editorial notes are separately inspectable.
- A Popular view ranks only examples with saved engagement counts; missing dates and likes are never filled in.
- Methodology and CLI dialogs, command copying, and labelled JSON state export. Export includes only state derived from received events, not unrevealed fixture results.
- Keyboard shortcuts: Cmd/Ctrl+K focuses the claim input; Cmd/Ctrl+Enter previews a matching example.
- Locally bundled fonts; no external font service.

## What the preview does NOT do

There is no backend connection, live retrieval, model inference, or Railway deployment yet. Arbitrary claims are not sent anywhere and do not get fabricated results. Only the curated examples can run.

The remaining simulated fixtures in `src/demo.ts` combine documented historical measurements from `../demo/cases.jsonl` and `../README.md` with example text and hand labels from `../eval/pairs.jsonl`, plus dates from `../tests/fixtures/corpus.json`. This is **not a captured event stream**. Playback timing is simulated. `src/demo-events.ts` contains deterministic, explicitly illustrative volume data because the project has no complete saved monthly curves. Annual counts sum the illustrative months; they are not API measurements. The timeline discloses this, and exports include the same warning.

A selected timeline period spotlights observations with matching saved dates; it does not turn the illustrative volume into a measured count of those observations. Undated references stay visible.

The saved frontier snapshot has no model scores: its annotations are explicitly editorial. The other examples' displayed hand labels are not current model predictions. Query-match volume is not independent corroboration. Earlier phrase matches are not established claim origins.

## Saved frontier example and offline backup

The default example now uses `../demo/recordings/pace-the-frontier/snapshot.json`, collected from X's public syndication endpoint on **2026-09-18**. It includes Dario's announcement, earlier wording from roon, and selected reactions from Musk, Altman, Sanders, Hassabis and Hwang. Raw responses and their hashes are retained alongside it. See the [capture README](../demo/recordings/pace-the-frontier/README.md) for exact links, verification, limitations, and deliberate refresh instructions.

This is a **saved source snapshot, not a recorded production/model run**. Text, authors, publication times, quote IDs, and likes come from the captured payloads. Long-post excerpts are marked. Replay timing and commentary are authored. Timeline totals count this selected sample only; there are no platform-wide activity measurements.

To prepare for a complete hosting/network outage:

```bash
npm run build:offline
```

Copy `dist/claimtrace-offline.html` somewhere safe and open it directly in a browser. It includes the application, source snapshot, styles and fonts in one file. No server, credentials, model service, or Node installation is needed to open the built file. Source links still require internet. Build/dependency installation requires preparation beforehand, and a later regular build clears `dist`, so retain a separate copy for judging.

## Main files

- `src/App.tsx`: navigation, overview, method/CLI dialogs, and state export.
- `src/investigation-state.ts`: shared data types, normalized event contract, pure reducer, and per-run sequence/terminal guards.
- `src/demo.ts`, `src/demo-events.ts`: curated illustrative fixtures and their simulated event schedule/timeline.
- `src/frontier-recording.ts`: saved X snapshot adapter, editorial notes, source-derived sample counts and replay events.
- `scripts/build-offline.mjs`: packages the production build into standalone HTML.
- `src/useEventPlayback.ts`, `src/PreviewInvestigation.tsx`: local event delivery, pause/show-all/replay, and selection of the saved snapshot versus illustrative examples. Replay resets state and presentation; changing sources remounts the controller.
- `src/Investigation.tsx`: data-only three-column workspace, lineage, source updates, and ID-based inspection.
- `src/Timeline.tsx`: supplied monthly buckets, coverage-aware annual aggregation, hover/focus inspection, and period selection.
- `src/StreamText.tsx`: isolated animation of received text; no access to full fixture answers or event schedules.
- `src/evidence.ts`, `src/Dialog.tsx`: shared source link/label helpers and native dialogs.
- `src/styles.css`, `src/investigation.css`, `src/timeline.css`: shared visuals, workspace layout, and timeline styling.

## Later integration

The frontend now derives its state from normalized ordered events. This contract is **not yet a parser or adapter for Python NDJSON**: the backend lacks some stable IDs and metadata, and its `shape`/`cascade`/`score` fields still need explicit mapping. No network transport has been implemented.

Events carry a run ID and increasing sequence number. Duplicates, older events, other runs, and updates after a terminal outcome are ignored. Post/observation updates preserve first-arrival order. A score's `postId` references the run-local `Evidence.id`, not the optional numeric X `Evidence.postId`. Missing metadata does not erase previously supplied metadata; a replacement judgment can clear a now-missing rationale. Fatal errors and stops preserve partial evidence.

An `activity` event replaces the current monthly dataset; its buckets belong to one query/window. Coverage is `complete`, `partial`, or `unavailable`, and counts may be null. Do not combine incompatible queries or extrapolate missing months. Provenance distinguishes illustrative volume, measured activity, and saved-post sample counts separately from preview/recorded/live execution. The current recorded example carries additional source-snapshot metadata so it cannot be mistaken for a recorded pipeline execution.

A future recorded/live adapter can drive the same reducer and `Investigation` view. Keep measurements, semantic judgments, and generated prose distinct. The view does not offer playback controls for live runs; actual cancellation and the broader loading/error interface remain future work. The eventual Railway container can serve these static assets alongside the Python API.

Never put provider credentials in this frontend, including `VITE_*` variables: those are compiled into browser assets. No credentials are required to run this preview.
