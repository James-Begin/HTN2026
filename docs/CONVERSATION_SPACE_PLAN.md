# Conversation Space — an interactive 3D fan of posts

## Recommendation

Upgrade Neighborhood into **Conversation Space**: a long time axis, a seed anchored at time zero, and posts spreading around that axis according to their relationship to the seed's captured text. Users orbit the scene, inspect actual posts, follow recorded quote/reply links, and replay the captured conversation through time.

Use a **semantic fan** as the default visual encoding, with a simpler **metric-axes** alternative for inspection. Use Three.js through React Three Fiber, not a force-directed layout. Start with the saved corpus and prove the visual interaction before connecting incremental inference.

**Planning only.** No application implementation, dependency installation, model calls, tests, commits, or pushes are part of this task. Existing uncommitted stabilization changes remain intact. Public-access/security work remains deferred as requested. Any later paid embedding collection requires explicit authorization.

## 1. What the user sees

```text
Activity & posts     Conversation Space

[Live discovery / Replay time]   [Fan / Metric axes]   [Links] [Fit] [Reset]

                interactive 3D canvas                 selected post
                                                     author · handle
       earlier     seed      later                   actual text
    ────────────────●──────────────────→ time          captured metrics
                       •      •                      quote / reply links
                          •        •                 Open context / X
                       •      •

                  semantic departure

[publication-time scrubber / selected window]      captured · placed · pending
```

The default camera is oblique: the time axis reads broadly left-to-right while the semantic plane has visible depth. The scene should look like an explorable conversation, not a spinning scientific dashboard.

- A restrained dark background, thin axis/grid marks, small points, and a distinct seed ring.
- Close semantic matches stay near the centerline; more different captured text sits farther away.
- Different projected semantic directions occupy different angles around that line.
- Recorded quotes/replies form curved links through the space.
- Hover identifies a post; selection populates a readable HTML inspector. Full source context uses the existing explicit context action.
- The inspector is **non-modal**, so the user can keep orbiting while reading. The existing modal remains useful for detailed quote/source inspection.
- Avoid permanent text labels or avatar textures on every point. Show names for the seed, selection, and hover.
- No generated per-post headlines, narrative summaries, or typewriter presentation.

The geometry must be data-derived. Do not multiply spread by elapsed time merely to manufacture a widening cone. Some conversations remain close to their initial wording; others branch immediately.

## 2. Current code: reuse and gaps

Verified against the current working tree, including the local stabilization changes:

| Existing foundation | How it helps / what changes |
|---|---|
| `web/src/Neighborhood.tsx` | Existing selection, source inspection, link-type controls, and search are reusable interaction patterns. Replace the SVG layout rather than extruding its role rows into 3D. |
| `web/src/graphData.ts` | Reuse canonical post IDs and observed-reference extraction. Do not reuse equal-rank time spacing or role-lane coordinates as measured geometry. |
| `web/src/Sequitor.tsx` | Already receives `posts.upsert`, guards run/sequence identity, preserves partial results, and opens source context. Add a graph-specific model and presentation clock rather than tying the scene to the feed's ten cards. |
| `sequitor_server.py::embed_texts` | Optional Baseten embeddings and a persistent text cache exist. Vectors are not included in saved run JSON or current post events. |
| `sequitor_server.py::rank_posts` | Scores can be computed per seed/post independently. Whole-corpus reranking is not mathematically required for incremental coordinates. |
| `sequitor_server.py::period` | Raw retrieval pages already stream before final curation. Embedding/ranking is currently staged after accumulated retrieval, not emitted per initial batch. |
| `web/scripts/build-offline.mjs` | Existing single-file packaging can support a precomputed scene, but currently rejects multiple JavaScript chunks and does not package runtime workers/WASM/assets. |

Important evidence:

- The default normalized corpus contains **539 unique posts**, including the supplemental humor. None of the saved posts has numeric relevance scores or embedding vectors.
- The current story artifact selects **150 IDs**; the component then limits its visible sample to **42 nodes**. The new scene must not accidentally inherit either restriction.
- The story's **25 similarity edges are TF-IDF wording comparisons**, not neural embedding relationships.
- Some references point to posts not captured, and an earlier captured post predates the Dario seed. Missing references and negative elapsed time are normal cases.
- `semanticScore` can currently mean **token overlap when embeddings are unavailable**. `rankingScore` is a hybrid retrieval score. Neither field alone establishes genuine embedding similarity.
- Existing live exploration initially retrieves a selected day. A multi-day fan needs saved multi-day data or an explicit bounded adjacent-window collection step; a 3D renderer cannot create temporal breadth that was not fetched.

## 3. Axes and anchor semantics

### Time is always the long axis

Use actual publication instants, not discovery order, likes order, array indexes, or Snowflake inference for an unverified post:

```text
elapsed = post.publishedAt - reference.publishedAt
x = timeScale × elapsed
```

`timeScale` is fixed for the run's requested time window. Axis labels display actual elapsed minutes/hours/days and UTC publication times. Changing the camera does not change coordinates.

- The supplied seed post is the default reference at `x = 0`.
- Posts before it have negative coordinates. The seed is a reference, not a claim to be the earliest origin.
- Never change the anchor automatically when a newly retrieved post has more likes.
- For a topic/text input, ask the user to choose a captured reference post, or offer a clearly labelled reference among retrieved posts. Until then, use absolute UTC time and an unanchored/pending semantic state.
- Never turn the input text into an authored post or invent its publication time.
- **Focus on a post changes the camera, not the reference.** Changing the reference is a separate explicit operation that creates a new layout version.
- If results extend beyond the initial window, extend the visible axis or offer Fit; do not rescale all existing points on every arrival.

### Recommended default: semantic fan

There is one time coordinate and a transverse semantic plane. The plane's **radius** has an exact seed-relative interpretation; its **angle** is a lossy projection used to separate directions.

For normalized embeddings `eᵢ` and reference embedding `e₀`:

```text
sᵢ = clamp(dot(eᵢ, e₀), -1, 1)       # cosine similarity
rᵢ = R × sqrt((1 - sᵢ) / 2)          # scaled unit-vector chord distance

uᵢ = eᵢ - sᵢ × e₀                   # direction orthogonal to the seed
q₁ = dot(uᵢ, b₁)
q₂ = dot(uᵢ, b₂)
θᵢ = atan2(q₂, q₁)

yᵢ = rᵢ × cos(θᵢ)
zᵢ = rᵢ × sin(θᵢ)
```

`R` is a fixed display radius. `b₁` and `b₂` are a frozen orthonormal projection basis, fitted from a reference set of residual vectors.

This gives the desired effect:

- The seed is at the origin.
- Similar text lies near the time spine.
- Semantically different responses lie farther away.
- Different projected directions separate around the spine instead of piling into a single vertical strip.

**Honest labels matter:** label the transverse axes “semantic direction A/B,” not independently “similarity” and “relevance.” Show seed cosine and elapsed time in the inspector. Radial rings can explain departure from the seed. This is a radial semantic visualization, not a distance-preserving linear embedding of every pair of posts.

A criticism can be semantically close to the seed; an approving short quote can be textually distant. Distance does **not** mean disagreement, irrelevance, falsehood, or influence. Nearby points do not necessarily belong to one social community.

### Projection stability

Do not refit PCA/UMAP or run a force simulation on each arrival. That would rotate/move the scene while the user is reading it.

- **Saved capture:** fit once on its reference vectors; save the basis identity and final coordinates with the artifact.
- **New live run:** show received posts in a distinct pending rail at their correct time while gathering a small, varied calibration batch. Fit once, then freeze the basis.
- Subsequent posts are transformed through the frozen basis. Existing coordinates remain unchanged unless their own source/feature revision changes.
- Fit PCA without whitening on residual vectors. Use seed-relative projected coordinates, not an unadjusted centered PCA output that would displace the reference. Fix component signs deterministically and persist the resulting basis rather than recomputing it on reconnect.
- Record the calibration corpus/hash. Early sampling can bias the angular view; expose that limitation in details.
- Zero/invalid embeddings, insufficient independent directions, or negligible projected direction remain explicitly unresolved. Do not assign a fake semantic angle from a post-ID hash.
- Near-identical text can legitimately coincide at the centerline. Use selection/overlap handling rather than altering measured positions.
- A later “recompute layout” operation must be explicit and versioned. Do not implement it in the first slice.

### Simpler alternative: metric axes

Offer a transparent alternative using:

```text
X = elapsed publication time
Y = semantic distance from the seed
Z = lexical distance from the seed
```

This can distinguish reworded discussion from similar wording, but the metrics remain correlated; it is not an independent topic map. It is easier to explain and avoids a projection basis.

Do not default to similarity versus hybrid relevance: the current relevance score partly reuses similarity, and its value also changes with retrieval scope and model availability. If engagement is an optional axis later, label it as captured engagement, not semantic spread. Prefer capped logarithmic **point size** for engagement so popularity does not dominate the geometry or hide ordinary accounts.

## 4. Similarity inputs and an honest offline prototype

The renderer needs a real feature artifact, not invented coordinates attached to existing posts.

### Semantic path

Reuse the server's embedding interface once a working deployment and bounded inference budget are authorized. No language-model retraining is required.

- Use one embedding model/deployment and one text-encoding policy per layout.
- Validate provider response indexes, finite numeric vectors, common dimensions, and nonzero norms before normalizing.
- Cache by the actual encoded text hash, model/deployment revision, and encoding policy. Existing code hashes full text but sends a truncated input; the new feature metadata must make the effective input explicit.
- Store the reference input/hash, including whether it is an excerpt. Fuller source text must not silently replace the reference embedding halfway through a run.
- Keep seed similarity separate from hybrid retrieval relevance and same-claim scores.
- Encode captured authored text as the baseline. Do not append the full seed to every candidate; that would artificially pull all candidates toward it.
- Short quotes such as “Dario is right” remain understandable through their observed edge even if their own-text similarity is low. Contextual embeddings can be a separately named policy later, only using captured quote/reply context.

### No-provider visual slice

The saved corpus has no embeddings. For the first visual prototype, compute a local TF-IDF representation from captured source text and produce a frozen **wording fan**, clearly labelled as such. The existing wording builder contains useful tokenization/weighting ideas, but its sparse pairwise edge list is insufficient to reconstruct a full coordinate map.

Do not present TF-IDF or Jaccard as neural semantics. Do not mix fallback wording coordinates into an otherwise semantic scene when an individual embedding fails: keep those posts pending/unavailable, or explicitly switch the whole layout mode.

The deployed Python image currently installs no numerical packages. A live PCA implementation therefore needs a deliberate runtime choice. Recommendation: use a small explicit NumPy dependency for basis fitting when the live projection slice is approved; keep artifact generation separate from frontend builds. Do not import the training stack or introduce browser WASM merely to get the first scene working.

## 5. What streams, and in what order

There are **two clocks**:

1. **Publication time:** where a post belongs in the conversation.
2. **Discovery/processing time:** when retrieval, embedding, or ranking actually returned it.

Search results currently arrive newest-first or popularity-first. Strict global chronological arrival is impossible while future retrieval batches can reveal older posts.

### Live discovery mode

- Insert a post at its correct time coordinate as soon as it is received.
- Before semantic features arrive, render it in a clearly separate pending rail, not at radius zero (which would imply perfect similarity).
- On feature arrival, move only that post into its measured position at the **same X coordinate**, using a short transition if motion is enabled.
- A newly discovered older post appears behind the current frontier. Label this as a backfill rather than pretending the system found it earlier.
- Batch presentation may sort newly received items by parsed publication instant and ID; that does not make the entire search globally chronological.
- Never launch an unconnected point out of the seed as an animation: it would suggest a propagation edge that may not exist.

### Replay time mode

For the known captured corpus, sort by parsed UTC publication instant with stable ID ties and reveal posts with a moving time cursor. Reveal a reference edge only when its required endpoints are available and the referencing post has reached the cursor.

This is the clean chronological fan-out for presentation. Provide play/pause, scrub, restart, and a rate control. The replay explains the order of the captured posts, not when likes were earned or when the original API calls completed.

During a live search, replay can operate over the currently known subset, visibly labelled incomplete. Offer a clean chronological replay of the completed captured result afterwards.

### If strict chronological live delivery is later required

Retrieval must be scheduled in chronological windows, buffering each window across all enabled branches before releasing it. Mark a window complete only when its declared retrieval scope is complete; capped pages cannot establish that no older results will arrive. That increases latency and can still be incomplete under a budget.

**Recommendation:** do not make that complex guarantee in the first implementation. Use honest live backfills plus deterministic replay.

### Keep controls distinct

- **Pause animation:** freeze the visual playhead; retrieval may continue, with a visible queued/received count.
- **Stop search:** stop the run's further retrieval/inference through its lifecycle; retain received results.
- Orbit, hover, search within captured posts, and time scrubbing make **no provider calls**.
- Graph time filtering is independent of `chooseDay`, which can request paid period data. Loading another period must be an explicit data action.

## 6. Incremental backend integration

Recommended flow:

```text
resolve seed → establish reference/text policy
                  ↓
retrieve a page → deduplicate → emit source posts immediately
                  ↓
            bounded feature queue
                  ↓
        cached/batched embedding inference
                  ↓
      seed similarity + frozen projection
                  ↓
        emit feature updates for those IDs
                  ↓
     optional curation/relevance updates later
```

Do not wait for the hosted curator or trained same-claim reranker before placing a node. Curation can update color/filter metadata later without changing the geometry.

Concrete changes:

- At each retrieval branch's returned batch in `Sequitor.period`, enqueue only new or text-changed posts for feature computation.
- Reuse the seed embedding and cached post embeddings. Compute features for the batch; do not repeatedly rerank/embed the full corpus just to place new points.
- Coalesce model work into bounded microbatches with a short flush interval, rather than a separate request per post. Exact limits are tuning choices, not measured performance guarantees.
- Prefer a serial batch implementation first. Add overlap between retrieval and embedding after the visual slice works.
- For overlap, separate the stateless provider call from `embed_texts`' cache mutation and `save()`. Workers must not concurrently overwrite the shared JSON cache or try to reacquire the application lock held by the investigation.
- Use immutable worker results and one owner for cache writes. An ordered event publisher assigns the existing run sequence to source, feature, and lifecycle events.
- Cancellation drops unsent feature work; late results cannot enter a replacement run. Any model error leaves readable source posts and an explicit unavailable feature state.
- `run.completed` must wait until accepted feature work has settled, or explicitly finish with unavailable/partial features. The current frontend correctly ignores events after a terminal result; do not weaken that guard to accept late model updates.
- Cached execution must publish available feature snapshots too, not only raw source posts. Missing cached features need an explicit processing state, not a false completed semantic scene.

For temporal breadth, add bounded adjacent-day retrieval using the existing query/branch scope. Preserve the existing measured-volume query separately. A graph of captured candidates is never the platform-wide volume curve.

## 7. Data contract and state ownership

Keep source posts, semantic features, graph references, and presentation state separate.

Proposed additions (new types, not existing API fields):

```ts
type LayoutSpec = {
  id: string
  referencePostId: string
  referencePublishedAt: string
  referenceTextHash: string
  timeWindowUTC: { start: string; end: string }
  kind: 'semantic-fan' | 'wording-fan' | 'metric-axes'
  featureMethod: string
  modelRevision: string | null
  textPolicyVersion: string
  basisId: string | null
  calibrationCorpusHash: string | null
}

type SpatialFeature = {
  postId: string
  sourceTextHash: string
  layoutId: string
  revision: number
  status: 'pending' | 'ready' | 'unavailable'
  seedCosine: number | null
  lexicalSimilarity: number | null
  angleRadians: number | null
  directionQuality: number | null
  semanticYZ: [number, number] | null
}

type RecordedReference = {
  id: string
  referencingPostId: string
  referencedPostId: string
  kind: 'quote' | 'reply'
}
```

An unanchored topic search stays in an explicit pre-layout state until an actual reference is chosen. Unknown publication times are not coerced to the seed time.

Proposed event additions:

- `graph.layout.ready`: frozen layout metadata; establishes feature/model/basis identity.
- `graph.features.upsert`: versioned feature updates keyed by post ID and text hash.
- `graph.references.upsert`: optional explicit references when not already derived from post fields.
- `graph.coverage`: captured scope/window/partial status and unresolved processing counts, not invented total conversation size.

Retain existing source and terminal events. The graph store must:

- Keep IDs as strings; deduplicate independently of feed ordering.
- Merge fields without replacing a fresh record with a stale seed/saved-period object.
- Reject foreign runs, older revisions, incompatible layout IDs, and features for obsolete text hashes.
- Hold features/references that arrive before their posts; attach them when matching sources appear.
- Preserve missing reference targets as unresolved records rather than silently deleting the relationship.
- Track retrieved, feature-ready, pending, filtered, and rendered counts separately.
- Maintain append-only render slots per run; GPU slot IDs must not change when a post's rank changes.

**Do not ship full embedding vectors to the browser by default.** Compute projection features server-side and bundle the same compact results for offline playback. Camera changes, view presets, and timeline filtering need no vectors or inference. Offline arbitrary re-anchoring is not supported unless the necessary vectors or alternate layouts are deliberately included.

## 8. Web renderer and interaction specifics

### Recommended stack

- `three` for geometry, cameras, buffers, curves, and raycasting.
- `@react-three/fiber`, selecting a release compatible with the project's React generation.
- `@react-three/drei` for controls and small helpers; import narrowly and verify peer compatibility when pinning dependencies.

The R3F v9 migration guide establishes React 19 compatibility. Do not assume arbitrary latest versions are mutually compatible without checking their peer dependencies at implementation time.

A force-graph package is attractive for a quick generic network, but this feature needs deterministic metric coordinates, frozen axes, custom streaming, and precise source inspection. A force simulation would work against those requirements. Direct Three.js is also viable, but R3F fits the existing React application and makes canvas/HTML composition easier.

### Scene components

```text
ConversationSpace
├── graph store + playback controller       (outside the canvas)
├── controls / status / time scrubber       (HTML)
├── Canvas
│   ├── SceneCamera + OrbitControls
│   ├── TimeSpine + ticks + semantic guides
│   ├── PostInstances
│   ├── ReferenceCurves
│   ├── PendingRail
│   └── SelectionHighlight
└── SelectedPostInspector                   (HTML, source-first)
```

- Use instanced low-detail glyphs rather than a React mesh subtree for every post.
- Maintain `postId ↔ instanceId` mappings. Raycast selection resolves back to the source post; hover never overwrites permanent selection.
- Keep the selected/seed highlight in a small separate layer so emphasis does not require rebuilding all geometry.
- Update GPU buffers for changed instances and mark them dirty. Recompute bounds after changes that affect culling/picking.
- Store camera orientation, target, and zoom separately from post data. Incoming posts and tab changes should not reset the user's camera.
- Start with demand rendering. Invalidate on camera movement, data changes, and active transitions; stop requesting frames when idle.
- Mutate animation buffers/Three objects during frames instead of calling React state setters for every point every frame.
- Dispose geometries, materials, controls, and renderer-owned resources on teardown. Handle WebGL creation/context-loss failure with the readable feed or 2D fallback.

### Interaction

- Drag empty space to orbit; modifier/right drag to pan; scroll/pinch to zoom.
- Distinguish a drag from a click with a small movement threshold. Orbiting must not accidentally select or move a post.
- Click a point to inspect; double-click or a Focus action centers the camera on it.
- Do **not** drag data points off their measured coordinates. Selection and camera movement are the intended interactions.
- Provide Reset, Fit, and reference-focus controls.
- Add side/time view and end-on semantic view presets. Clearly label that the end-on view collapses time.
- Avoid auto-rotation. Smooth camera transitions should be brief and disabled under reduced-motion preferences.
- Mobile uses a compact inspector/bottom panel and explicit camera controls; touch interception is limited to the canvas, not the whole page.
- Keyboard users get a captured-post list/search, selection controls, time controls, and camera presets. The canvas is not the only way to navigate evidence.

## 9. Curves, clutter, and perceived propagation

Reuse captured `parentId` / `quotedPostId`. Do not treat a model's proposed `graph.observed` edge as authoritative unless it agrees with actual captured reference fields.

- Store reference direction as **referencing post → referenced post**, matching the API semantics.
- If replay animates earlier post → response, distinguish that display direction from the stored reference direction. Inspector text must still say exactly “quotes” or “replies to.”
- Use cubic Bézier curves with stable control-point offsets derived from edge identity. Bending is a drawing choice, not a reconstructed route through an audience.
- Keep time control points monotonic for normally ordered references. Flag inconsistent timestamps rather than inventing chronology.
- Render ordinary edges as subdued batched segments; draw selected incident curves more prominently, optionally with thicker screen-space lines and directional markers.
- Avoid a mesh tube for every edge and avoid an all-pairs semantic graph.
- Default to recorded edges. Optional shared-wording/semantic neighbor links remain a separate, clearly inferred layer, hidden by default.
- Missing targets remain in the inspector as unresolved source links. Never route them to the seed just to complete the picture.
- Prefer selected-node neighborhoods and explicit link filters when the seed star becomes dense. Disclose hidden edges and keep every recorded link reachable in the inspector.
- Exact overlapping points use an overlap list or an explicitly labelled display expansion. Do not jitter timestamps or metric values just to make every marker visible.

The fan shows the evolution of **captured content and recorded references**, not who saw a post, who copied it, or the causal diffusion path across X.

## 10. Offline build and rendering budget

The first target is the actual saved corpus, not an unverified promise to render millions of posts.

- Bundle a projection artifact containing source-capture hash, layout metadata, per-post feature/text hashes, and coordinates. Verify its identity before attaching it to source records.
- Import that artifact at build time so the existing standalone HTML can include it.
- Keep a single application bundle for the initial implementation. Dynamic imports currently break the offline packager; browser worker entry points, WASM, external fonts, and textures also need special handling.
- Do not introduce runtime CDN dependencies for Three.js, fonts, shaders, or the scene dataset.
- Keep generated projection output separate from the original source snapshot and its capture hashes.
- Limit device pixel ratio, labels, visible edges, and decorative effects before considering more complex rendering. Avoid bloom/shadows/remote avatar textures in the first slice.
- If larger captures require sampling or level-of-detail later, preserve the seed, selection, and observed neighbors; disclose counts and retain search access to hidden posts.
- Keep the feed/2D view available when WebGL is unsupported or uncomfortable for the user.

## 11. Implementation map

Existing files to touch only as needed:

| File | Planned responsibility |
|---|---|
| `web/src/Sequitor.tsx` | Connect graph events and the canonical captured corpus; share post selection; keep a user's Space view open during a new search rather than always forcing the feed. |
| `web/src/graphData.ts` | Shared source/reference types and helpers; retain the old 2D layout as fallback rather than overloading it with 3D state. |
| `web/src/Neighborhood.tsx` | Keep during the first slice as a 2D fallback; later reuse suitable inspector controls. |
| `sequitor_server.py` | Emit per-batch features, expose feature provenance, and separate provider calls from mutable cache writes before concurrency. |
| `web/package.json`, `web/package-lock.json` | Add verified compatible rendering dependencies when implementation is approved. |
| `web/scripts/build-offline.mjs` | Preserve the single-file contract; only extend for new asset types if genuinely required. |
| `Dockerfile` | Add the small numerical runtime dependency if live PCA fitting is adopted; no deployment operation implied. |

Proposed new files (not currently implemented):

- `web/src/ConversationSpace.tsx`: canvas/HTML composition and fallback.
- `web/src/conversation-space-state.ts`: layout/source/feature/reference state and revision rules.
- `web/src/conversation-space-layout.ts`: deterministic coordinates and axis/picking helpers.
- `web/src/useConversationPlayback.ts`: publication-time cursor versus live-discovery presentation.
- `web/src/conversation-space.css`: graph workspace and inspector styles.
- `demo/recordings/build_conversation_space.py`: reproducible offline feature/projection artifact generation.

Keep the first component split modest; extract render layers when their complexity warrants it. Do not refactor the CLI, old research pipeline, or unrelated frontend areas for this feature.

## 12. Delivery sequence — visual first

### Slice A: make the saved conversation compelling

Build the 3D canvas, real elapsed-time axis, orbit/pan/zoom, picking, source inspector, curved observed links, and frozen wording-fan artifact. Use the captured corpus without the old role-map sampling cap. Add a chronological replay and a clear wording-layout label.

**Exit:** the user can rotate a real saved conversation, follow a quote, read its actual post, and watch it unfold in publication order. No paid calls are necessary for this slice.

### Slice B: replace wording coordinates with genuine semantic features

After endpoint/budget approval, embed the saved capture, generate a versioned semantic layout, and compare it visually with the metric-axes view. Validate reference/excerpt text policy and angle stability before spending on arbitrary live searches.

**Exit:** a precomputed semantic scene with honest metric labels and preserved source provenance; no need for neural model training.

### Slice C: make discovery grow the scene live

Add feature events, pending placement, immutable batch processing, score/projection revisions, and explicit backfill behavior. Begin with serial per-batch inference; overlap retrieval/model work only after that flow is coherent. Add bounded adjacent-window collection so the live view has actual temporal breadth.

**Exit:** raw posts appear promptly at the right time; features arrive independently; old points and camera remain stable; stop/reconnect preserve received evidence.

### Slice D: polish the presentation

Tune contrast, point scale, clutter controls, camera presets, responsive inspection, reduced motion, and the offline package. Consider richer semantic-neighbor exploration or explicit reference changes only after the core scene is convincing.

### Lean verification

Respect the preference to avoid excessive testing. At each slice, do a build and a short targeted walkthrough of the real saved example. Focus on coordinate stability, an earlier-than-seed post, source fidelity, selection/orbit distinction, and replay ordering. For the streaming slice, use a small mocked out-of-order/feature-failure sequence before one authorized live trial. Do not create a large testing harness or promise performance numbers before measuring the actual scene.

## 13. Decisions to approve

Recommended defaults:

- **Name:** Conversation Space, upgrading the Neighborhood tab.
- **Primary layout:** semantic fan; metric axes as an inspection alternative.
- **Origin:** the supplied seed, fixed for the layout; earlier posts remain visible at negative time.
- **Live behavior:** immediate discovery placement with honest backfills; separate publication-time replay.
- **Rendering:** React Three Fiber/Three.js with fixed coordinates and instanced glyphs.
- **First build:** saved-data wording fan, so the visual concept is reviewable before model integration or paid inference.
- **Scope:** keep the current feed and source cards; no security/deployment work and no commits/pushes without instruction.

## Technical references consulted

- [React Three Fiber: scaling performance](https://r3f.docs.pmnd.rs/advanced/scaling-performance) — demand rendering, invalidation, instancing.
- [React Three Fiber: v9 migration guide](https://r3f.docs.pmnd.rs/tutorials/v9-migration-guide) — React 19 compatibility and lifecycle considerations.
- [Three.js: OrbitControls](https://threejs.org/docs/pages/OrbitControls.html) — orbit, pan, dolly, touch, camera limits.
- [Three.js: BufferGeometry](https://threejs.org/docs/pages/BufferGeometry.html) — GPU buffers, bounds, disposal.
- [Three.js: instancing and raycasting example](https://github.com/mrdoob/three.js/blob/master/examples/webgl_instancing_raycast.html) — instance-based picking.
- [scikit-learn: IncrementalPCA](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.IncrementalPCA.html) — distinction between changing a fitted basis and transforming new samples through an existing basis. Incremental refitting is deliberately not the default for the live view.
