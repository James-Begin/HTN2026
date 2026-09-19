# Sequitor — next steps after the repository sync

Reviewed September 19, 2026, against `a627017263295a3ff071be59d229e1aacded3b46` (`Polish activity control behavior`).

This replaces the earlier product-reset plan, which described much of the now-implemented interface as future work. **This is a plan, not approval to change application code, buy API usage, train/deploy models, or modify credentials.**

## Repository state

- Repository: `/Users/james.begin/dev/claimtrace`; remote: `git@github.com:James-Begin/HTN2026.git`.
- The remote initial commit was rewritten from local `00a6078` to `b485eea`; their tree hashes are identical. Local history was preserved as `backup/pre-pull-00a6078` before synchronizing `main` to `origin/main` with `git reset --keep`.
- Application source is synchronized to the reviewed revision. This plan is the only subsequent working-tree edit; it has not been committed or pushed.
- Keep **Sequitor** as the browser name. Do not reopen the earlier Offshoot/Wake naming exercise or rename the legacy Python CLI.

## What actually changed

| Area | Current implementation | Important boundary |
|---|---|---|
| Browser | `web/src/main.tsx` now mounts `Sequitor.tsx`: neutral-dark timeline/feed, original post cards, source/context drawers, optional graph | The older `App.tsx` and normalized investigation reducer are no longer the active browser path. Their tested lifecycle/accessibility behavior does not automatically protect this implementation. |
| Activity and rankings | UTC daily selection, Popular/Recent/Sequitor sorting, hourly activity, monthly aggregation | Monthly/hourly bars are non-selectable. There is no monthly top-post request or yearly navigation. Recorded hourly bars count captured posts, not measured platform activity. |
| Retrieval | OpenAI context planning, X counts/search, direct-conversation retrieval, bounded evidence-based expansion, zero-phrase context-count fallback | Counts measure one declared query; candidate retrieval spans additional queries and remains incomplete. |
| Models | Optional Baseten embedding route, lexical fallback, Chain adapter, cross-encoder and hosted-curation fallbacks | A successful Chain path bypasses the trained cross-encoder. Code and configuration do not prove an endpoint is currently deployed or available. |
| Streaming | `sequitor_server.py`: background jobs, SSE replay/cursors, cancellation flags, persisted event logs and caches | Cancellation is cooperative; persistence, public admission control, and cache completeness still need work. |
| Recordings | Larger Dario capture, separately collected humor, Wet Lab example, model-role/wording graph artifact | Do not equate saved candidates with complete rankings or observed propagation. |
| Packaging | Docker/Railway configuration, documented GitHub Pages demo, single-file `sequitor-offline.html` | Deployment instructions are not evidence of a deployed live service. Offline source cards work, but remote avatar/widget requests are still attempted. |
| Dependencies | Lockfile download URLs now use public npm | A fresh external `npm ci` was not revalidated during this review; the build used existing installed dependencies. |

**Recommendation:** retain this foundation. The next work is reliability and retrieval quality, not another redesign or server-framework migration.

## Immediate operational check

`SEQUITOR_HANDOFF.md` says the project page was published but not submitted, and gives an initial submission deadline of September 19 at 2 PM EDT. At this review's clock check, September 19 at 21:35 UTC, that documented deadline had passed. **Actual submission state and the event's current rules are [UNVERIFIED].** Confirm them in the logged-in event view or with organizers; do not assume either that publishing submitted the entry or that the handoff is still current.

Also confirm disclosure of pre-existing Claimtrace work and which Sequitor work was created during the event. Do not represent historical training or benchmarks as new event work.

The handoff's claim that credentials exist locally does not apply to this checkout: no root `.env` was present, and `X_BEARER`, `OPENAI_API_KEY`, and `BASETEN_API_KEY` were absent from the review process environment. No live-provider availability, account balance, or current deployment was verified.

## Priority A — stabilize the existing demo without paid calls

### Fix reproduced browser regressions

- **Invisible feed after a tab round trip.** Open Activity & posts, switch to Neighborhood, then return. The remounted feed remains at `opacity: 0`. The entrance observer only registers initial nodes (`web/src/Sequitor.tsx:317–328`). Attach observation to the actual mounted element, or remove the entrance hiding from essential content. Reduced motion must not be the only working route.
- **Restore accessible drawers.** Post/data drawers are overlay `<aside>` elements, not modal dialogs. Opening data details leaves focus behind the overlay; Escape does not dismiss it. Restore dialog semantics, focus entry/trapping/return, Escape, and background inertness. The legacy dialog implementation is a useful reference, not a reason to assume the new drawers already comply.
- **Isolate new searches from the Dario fixture.** `startStreaming` spreads the recorded fallback into a new live run, retaining its seed post, scope, query, capture time, and context plan until replacements arrive (`Sequitor.tsx:470–489`). Start from an empty run-specific state; clear old inspection and activity-loading state. A failed new search must never look like a Dario result.
- Separate run, period, and hourly request state. Reject stale context responses, clear loading on cancellation/resolution changes, handle malformed stream messages, and distinguish completed, stopped, failed, and reconnecting states. Closing a browser stream alone does not cancel server work.

### Correct source and display claims

- **Preserve excerpt metadata.** The live Dario seed has exactly the same text as the earlier capture marked truncated, but `textIsExcerpt` is false. Carry the known warning through recording merges, seed resolution, cards, and graph inspection; never reconstruct missing text. The live resolver currently hardcodes false (`sequitor_server.py:808–814`).
- The default sort is **Sequitor**, while the data drawer always says posts are sorted by captured likes. Make the description follow the active ranking. Recommended product default remains **Popular**, with semantic ordering optional.
- Treat pasted text as an input marker, not an authored X post with an invented publication time. Graph role labeling alone does not solve synthetic-source presentation.
- Keep the actual measured query immutable and separate from later search-plan revisions. Reconcile the saved run's query/plan mismatch without relabeling historical counts.
- Preserve unavailable versus zero and partial-period coverage in hourly/monthly displays. A failed hourly request must not become a measured zero; a partial month must not look fully covered. Keep UTC bucket boundaries explicit rather than silently relabeling them Eastern.

**Acceptance:** both examples and tab round trips remain visible; keyboard-only context inspection works; replay/stop/new-search/day changes cannot mix investigations; excerpt, source type, ranking, query, and missing-data labels agree with the records. Keep fixes local and validate with saved/mocked inputs first.

## Priority B — gate live access before attaching public paid credentials

This is a prerequisite for public live service, not a prerequisite for the recorded demo.

1. **Protect every relevant route.** The server currently has no authentication or per-user authorization on live runs, paid period/hourly GET requests, or job read/cancel routes (`sequitor_server.py:942–1022`). Add operator/session access control, appropriate origin/CSRF protections, bounded admission/concurrency, and event/cache retention. Recorded jobs also consume threads and disk and need limits. Merely hiding the search field is not protection.
2. **Agree on the real budget.** Code and `.env.example` default to **1,800 post reads and 48 counts calls**, an estimated **$9.48** at the repository's rates. README and the morning handoff still describe **600/20 and $3.20**. The Railway guide already reflects the larger defaults. Confirm the intended cap before changing it; align documentation with effective configuration. These are local X accounting estimates, not account-wide limits or current billing quotes. OpenAI/Baseten need their own bounded usage controls.
3. **Make the ledger fail closed.** Unreadable/malformed cache currently falls back to an empty ledger (`sequitor_server.py:155–159,342–354`). Verify writable persistent placement, reject corruption, distinguish explicit initialization from lost state, and reserve budget before requests with crash recovery. A volume environment variable alone does not prove durable storage. Do not delete the existing ledger to make a demo run.
4. **Bound every provider call and queue wait.** Add request timeouts, run deadlines, cancellation checks before dispatch/retries, and queued-job cancellation. X and fallback Baseten calls currently lack explicit network timeouts; a stalled call can hold the shared application lock.
5. **Make cached lifecycle and replay trustworthy.** Runs are cached before initial retrieval completes, but cache hits do not require a completed retrieval (`sequitor_server.py:772–884`). Persist explicit partial/complete/failed/stopped state, use collision-resistant request identities, and resume or clearly expose partial results. Snapshot event payloads before retaining them so memory replay agrees with disk replay. Keep period/model/ranking versions coherent; propagate Chain partial/error status.
6. **Use readiness, not API reachability.** The frontend enables live input after `/api/demo` succeeds; `/api/health` only reports credential presence. Expose storage readiness, remaining local budget, and enabled capabilities without secrets. Provider connectivity checks require an explicitly authorized budget if they incur charges.

**Acceptance:** unauthorized requests cause no provider work; queued/stopped jobs cannot dispatch another call; corrupt/missing expected ledgers block paid work; partial cache hits cannot claim completion; replay is deterministic; one operator-controlled service/replica has bounded, inspectable usage. Confirm account-wide usage separately.

Do not change shared credentials without explaining impact and obtaining confirmation. The previously chat-exposed Railway credential still requires secure rotation before authorized deployment; never paste it into the plan, source, browser configuration, or logs.

## Priority C — retrieve the conversation, not just the literal phrase

Use `docs/SEARCH_BRANCH_PLAN.md` as the retrieval design input, with these refinements:

- Represent announcement, reporting, commentary, humor, and wider-context queries as typed branches with seed/evidence support, UTC windows, purpose, separate count/read budgets, and per-branch coverage.
- Preserve the working zero-phrase context fallback. If all grounded scopes lack activity, return a no-evidence state rather than broad unrelated results.
- Search relevant adjacent periods, not just a peak day. Follow supported quote/reply references with visited-ID deduplication and a bounded expansion frontier; resolve missing referenced posts where permitted.
- Reserve retrieval and model-candidate capacity for ordinary accounts and playful adaptations. Current model paths select an early candidate slice; later branches can miss curation. Rank a branch-balanced candidate set, not only the first returned posts.
- **Do not use same-claim scoring to exclude jokes.** A successful same-claim reranker belongs among optional signals for appropriate branches, not as the definition of relevance.
- Treat the targeted “who up pacing they frontier” captures as regression evidence. The generic retrieval process should discover that kind of response; appending hardcoded saved humor does not demonstrate live retrieval recall. The separately remembered Gemini wording remains unverified.
- Measure precision and known-post recall against saved Dario/Wet Lab evidence before another paid run. Verify genuine source fidelity and independent relevant responses, not merely a pleasing model explanation.
- Keep one countable volume scope distinct from branch candidates. Never sum overlapping query totals. If broader counts cannot be measured defensibly, retain the honest phrase/context chart rather than claim total conversation volume.

The branch document proposes a per-post “why included” explanation. That conflicts with the earlier post-first/no-generated-prose brief. Prefer short provenance chips and optional query details; do not reintroduce generated paragraphs under posts. Move the visible OpenAI context card and match scores into details unless their prominence is now an intentional product decision.

**Acceptance:** Dario humor/criticism and Wet Lab-specific posts are found through documented generic branches, unrelated broad matches do not dominate the first screen, and every branch's cost/scope/truncation is inspectable. Only then authorize a bounded live comparison. Better retrieval comes before more training or model endpoints.

## Priority D — finish period exploration and graph fidelity

### Periods

- Introduce an exact interval contract with inclusive UTC start/exclusive end, scope version, ranking metric, capture version, and separate count/candidate coverage.
- Make a month selection request or use a cached monthly corpus and return up to ten posts published in that interval. Current monthly bars are display-only; do not present their existence as completion of monthly browsing.
- Preserve unknown metrics and stable ties. Label rankings **top retrieved**, unless retrieval completeness actually establishes a stronger claim. Likes are captured totals, not likes earned during the selected interval.
- Cache and cancel period work independently of the initial stream. Add yearly overview only after monthly interaction and missing-period semantics are reliable.

### Neighborhood

- Describe the current view as a **sampled chronological role map**, not a reconstructed spread/influence network or discovered communities. Solid links are observed references; dashed links are local shared-wording comparisons, not embeddings or proof of exposure.
- The story artifact selects 150 IDs, but the component further caps the visible sample at 42 nodes. Make captured/eligible/displayed totals distinguishable; the tab's corpus count is not the visible node count.
- Derive coordinates from a stable reference corpus and then filter/project. Current layout is recalculated from the sampled slice, so selection/layer/cutoff changes can move existing nodes (`Neighborhood.tsx:127–139`). The `referencePosts` prop is not used.
- Fix link inspection and counts: seed links are normally hidden, the inspector lists only a few links, and “more links on the map” can refer to links that are neither drawn nor reachable. Provide accessible pagination/search or explicit missing/hidden-reference state.
- Distinguish the graph's cumulative Eastern “Through” cutoff from the feed's selected UTC day. Do not silently treat them as equivalent windows.
- Version graph annotations by source text, model, and prompt as well as ID; maintain capture hashes and reproducible selection. Resolve real missing edges before adding more inferred lines.

**Acceptance:** changing focus preserves established coordinates; every claimed inspectable reference can be reached; time/filter/sample labels match their semantics; monthly selection returns the correct interval rather than just changing a histogram scale.

## Priority E — rehearse and package the reliable path

- Preserve the recorded-first browser and CLI. Keep provider keys server-side and avoid paid composer prose the UI does not need.
- Retain request manifests, raw source provenance where available, excerpt flags, and capture times for new collections, including separately added humor.
- Bundle the supported period results and permitted avatars/media, or use honest local placeholders. Explicitly disable API/widget/remote-image attempts in offline mode; online embeds should be optional, not required to inspect a source.
- Build and copy `web/dist/sequitor-offline.html` outside `dist` before another build clears it. Exercise the actual copied file with networking disabled, including tab return, date selection, context, and replay.
- Rehearse one concise path through a spike, a genuine response/offshoot, and recorded context. Keep source-backed limits visible without making methodological prose the main experience.
- Reconcile README/handoff/branch-plan claims with the reviewed implementation, actual submission status, and verified deployment capabilities. Do not claim a trained model, full ranking, stable graph, or network-free backup on the basis of configuration alone.

## Validation performed for this review

- Built the reviewed Git snapshot in an isolated temporary directory with existing `web/node_modules`: TypeScript, Vite production build, and offline packaging passed. Existing project `web/dist` was left untouched.
- Opened the generated single HTML file in Chrome with networking disabled from context creation. Saved posts, Wet Lab selection, and source fallback remained available; no uncaught page errors were observed in that exercise.
- Reproduced invisible feed on tab return and non-modal/Escape-inert data drawer. Confirmed monthly bars are disabled for selection.
- Checked desktop and mobile presentation; the checked mobile viewport had no horizontal document overflow. A settled initial-view axe scan reported landmark-region issues; this is not a full accessibility pass.
- The offline session attempted remote avatar/widget requests. They could not succeed with networking disabled, but this is **offline-capable, not request-free**.
- Confirmed the Dario excerpt mismatch and budget documentation mismatch directly against source/captures.
- Backend and graph risk findings above are static-review findings unless a runtime reproduction is explicitly stated. No live provider calls, deployment, model training, credential changes, or new repository test files were made. Historical test reports are not current live verification.

## Recommended next approval

Approve **Priority A: a saved-data-only stabilization pass** first, keeping the current branding and overall layout. In parallel with planning any live launch, settle Priority B's access and spend policy. Then implement branch-aware retrieval against saved inputs, followed by an explicitly budgeted live comparison.

Decisions still needed: whether Popular remains the desired default; whether generated context/match details should move out of the main view; whether live access is operator-only or intended for public users; and the authorized aggregate provider budget. Submission/deployment status must be confirmed separately.
