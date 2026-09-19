# Sequitor: Conversation Space

## What this is

Sequitor is a post-first conversation explorer. It lets someone inspect captured posts, reactions, jokes, criticism, and recorded quote/reply relationships around a reference post. The product is an exploration interface, not an AI-written credibility report.

**Conversation Space is the current interactive 3D prototype.** It places posts along a publication-time spine and around that spine using real pretrained text embeddings. The default presentation compresses gaps in the capture and expands the semantic spread into a cone. A source inspector keeps the original captured text and its provenance accessible while the camera remains usable.

The current browser opens this view by default. **Activity & posts** and **2D Neighborhood** remain available. The older Claimtrace interface and CLI remain in the repository, but the active browser entry point is `web/src/main.tsx` → `web/src/Sequitor.tsx`.

This document describes the implemented behavior. The earlier [Conversation Space plan](CONVERSATION_SPACE_PLAN.md) contains proposals, including features not yet implemented. In particular, this implementation now defaults to **Flow time + Cone spread**, rather than an exclusively linear-time, constant-radius metric view.

## The essential interpretation rules

- Every plotted post comes from the supplied post records. The viewer does not generate filler posts or invent publication timestamps.
- **Flow time is not a linear clock.** It preserves publication order but changes horizontal spacing to make dense captures readable.
- **Cone spread is not evidence that semantic disagreement grows over time.** It deliberately amplifies the display radius as posts move along the spine.
- The inspector's **seed cosine** is the underlying embedding similarity. Changing time spacing, cone settings, width, or camera position does not change it.
- Semantic similarity does not establish agreement, copying, influence, truth, or audience exposure. The projected angle does not establish a community or a topic cluster.
- Curved links represent recorded quote/reply references, not inferred diffusion paths.
- Captured likes are not credibility, and are not necessarily likes earned during the displayed period.
- Captured post counts are not the complete conversation and are not interchangeable with the separate query-volume measurements in Activity & posts.

For the least visually amplified interpretation, choose **Elapsed time** and disable **Cone spread**. Even then, angular projection is lossy: distance between arbitrary points in the rendered space is not their full embedding distance.

## What is implemented

- Instanced 3D post glyphs using Three.js and `OrbitControls`.
- Orbit, pan, zoom, picking, hover previews, focus, fit, reset, side view, and end-on view.
- A non-modal selected-post inspector with captured text, author, timestamp, likes when available, cosine, source link, and recorded neighbors.
- A separate source-context action that opens the existing modal context interface.
- Real saved embeddings for the Dario and Anthropic Wet Lab captures.
- Flow-time and elapsed-time spacing, adjustable cone spread, and publication-time replay.
- Source-backed quote/reply curves with Selected links, All links, and No links controls.
- Search and an HTML post list for selection without relying on canvas picking.
- An initial-rendering failure message when 3D cannot be created; source inspection and the post list remain available.
- A portable saved-data HTML build with no runtime model download or inference requirement.

**Not implemented:** incremental embedding of new live results, a live feature-event protocol, automatic expansion of retrieval across the whole conversation, automatic community detection, or a causal conversation tree.

## Captures and reference posts

The feature builder reads:

| Input | Role |
| --- | --- |
| `demo/recordings/sequitor-live.json` | Dario capture: top-level posts, saved periods, and seed |
| `demo/recordings/dario-humor.json` | Additional captured humor-search results |
| `demo/recordings/anthropic-wet-lab.json` | Separate saved example |

The generated `demo/recordings/conversation-space.json` currently contains:

| Layout | Reference post ID | Feature records |
| --- | --- | ---: |
| Dario | `2098773920774074715` | 539 |
| Anthropic Wet Lab | `2101089498725855375` | 19 |

The Dario reference is explicitly chosen. The Wet Lab builder chooses the real captured post with the highest captured likes, breaking ties by ascending ID. **That makes it a reference, not a claim that it originated the discussion.** The frontend uses the supplied seed when available; otherwise it chooses a captured reference by likes and ID.

The builder merges records by post ID, with explicit seeds taking precedence. It excludes synthetic input records. The frontend also excludes search-input placeholders from graph posts and requires a valid publication timestamp for a plotted point. Topic input text is not represented as an authored X post.

The graph receives the canonical merged post collection, not the small sample used by the older 2D view. Its data are not restricted to the selected feed day. During the outer recorded retrieval playback, the parent controls which posts have arrived so far. For the Dario example, a complete reference corpus is supplied separately to stabilize the time calibration.

Earlier-than-reference posts have negative time coordinates. They are hidden by default; **Include earlier posts** reveals them. Consequently, the visible count can be lower than the layout's total even with Show all selected.

The capture has dense hourly bursts and long gaps between retrieved posts. Those gaps are gaps in this saved sample, not evidence that nobody posted during them. Flow mode does not retrieve additional records to fill them.

## Embeddings: real local inference, no training

Builder: `demo/recordings/build_conversation_space.py`.

Model:

```text
Xenova/all-MiniLM-L6-v2
revision: 751bff37182d3f1213fa05d7196b954e230abad9
weights: onnx/model_quantized.onnx
runtime: ONNX Runtime, CPUExecutionProvider
```

The builder downloads the pinned model files from Hugging Face when necessary. It uses `numpy`, `onnxruntime`, and `tokenizers`; it does not require PyTorch, a hosted inference endpoint, or training.

For each distinct captured text:

1. Preserve the captured wording verbatim. Do not append thread context, reconstruct missing text, or substitute a summary.
2. Tokenize with the model tokenizer and special tokens.
3. Right-truncate to the model input policy's **256-token** limit.
4. Run the quantized ONNX encoder.
5. Attention-mask mean-pool token representations, including attended special tokens.
6. L2-normalize the resulting sentence embedding.

The current artifact marks one Dario input as token-truncated and no Wet Lab inputs as token-truncated. Neither layout currently has an unavailable projected direction.

**Source excerpt and model truncation are different warnings.** A source may already be an incomplete capture before tokenization. Separately, the model may truncate that captured text. Both conditions have their own inspector warning.

This is an English-oriented compact encoder used on multilingual and sometimes excerpted material. Humor, irony, short posts, URLs, and missing context can all make its similarities imperfect. No language model writes per-post headlines or explanatory prose for this view.

The supplied Baseten credential was not used or stored for this prototype. The local feature builder does not need it.

## How semantic coordinates are calculated

Let `e` be a unit post embedding and `e0` the unit reference embedding:

```text
s = clamp(dot(e, e0), -1, 1)        # seed cosine
r = sqrt((1 - s) / 2)              # base seed-relative departure
u = e - s * e0                     # residual direction
```

The builder fits a residual PCA plane once for a given calibration:

- Distinct final captured texts contribute once to calibration.
- SVD is fitted to centered residuals.
- Component signs are fixed by making the largest absolute loading positive.
- The original, uncentered residual `u` is projected onto the fitted basis.

For basis vectors `b1` and `b2`:

```text
theta = atan2(dot(u, b2), dot(u, b1))
y0 = r * cos(theta)
z0 = r * sin(theta)
```

The reference has cosine `1` and base coordinates `(0, 0)`. A non-reference text with no reliable direction gets null coordinates rather than an invented angle. The builder also records `directionQuality`, the fraction of residual squared norm retained in the angular plane; the current UI does not display that diagnostic.

The base radius has an exact relationship to seed cosine. The angle is a lossy, corpus-dependent orientation. The implementation is not a force graph, UMAP, or a continuously refitted clustering algorithm.

The basis is cached by model, input policy, reference text, basis policy, and calibration text hashes. Its identity is recorded as `basisId`. Rebuilding with a changed capture can produce a different basis; stability is not a promise across arbitrary artifact regeneration. During ordinary browsing and replay, the saved semantic coordinates are not refitted.

## How time spacing works

The reference timestamp is `t0`. On initial calibration, the nominal end of the axis is:

```text
tEnd = t0 + max(1 hour, 1.05 * (latest reference-corpus timestamp - t0))
axisLength = 150 scene units
```

The extra span is display padding, not measured activity coverage.

### Elapsed time

```text
x = 150 * (publishedAt - t0) / (tEnd - t0)
```

This is genuinely linear elapsed publication time. Posts are not rounded to days or hours. If posts cluster here, their captured publication times cluster. The original source timestamp remains the authoritative time.

### Flow time — default

Flow mode builds a monotonic spacing transform from the sorted unique reference-corpus timestamps plus `t0` and `tEnd`.

For each adjacent timestamp gap, measured in milliseconds:

```text
gapWeight = 0.35 + ln(1 + gapMilliseconds / 30000)
```

Weights are accumulated, translated so the reference is at zero, and scaled so `tEnd` is at `x = 150`. Piecewise-linear interpolation maps times between these calibration knots; the inverse mapping is used for ticks and replay.

This expands dense bursts and compresses long gaps. Equal timestamps still have equal X coordinates. No random jitter or replacement timestamps are used. **Equal distances in Flow mode need not represent equal time intervals.**

The transform is held fixed for the mounted view's reference frame, rather than recalculated from the currently revealed replay subset. Switching modes changes the display transform, not the source data. Remounting a live view with a different calibration corpus can produce a different Flow layout.

Later arrivals use that fixed mapping, with linear extrapolation outside the calibrated knots. Fully adaptive live framing and guide extension are not implemented; use Fit when necessary.

### Granularity and labels

The axis has fine tick marks and major elapsed-time labels obtained from the active transform. In Flow mode those labels are deliberately irregular in clock time. Hover and inspector timestamps include seconds and use UTC. Elapsed labels use day/hour, hour/minute, or minute/second combinations according to the interval size; they do not pretend to show every component of a long duration.

## How the cone works

The renderer turns saved semantic coordinates into display coordinates using a scale `G`:

```text
progress = clamp(x / 150, 0, 1)

Cone spread enabled:
    G = 22 * width * (0.25 + 1.65 * progress)

Cone spread disabled:
    G = 22 * width

renderedY = y0 * G
renderedZ = z0 * G
```

The default width is `1.2×`; the control ranges from `0.6×` to `2.0×`.

Important consequences:

- With the cone on, two posts with equal cosine can appear at different radii because they occur at different positions along the spine.
- With Flow time enabled, cone amplification follows **Flow position**, not linear elapsed time.
- Earlier posts use the cone's minimum scale; growth is capped beyond the nominal axis end.
- Turning the cone off restores a common radial scale within that view.
- Width does not change embeddings, cosine, or the underlying angle.

The faint longitudinal guide lines suggest the display envelope. They are not discovered branches or links between posts. The previous time-slice hoops were removed to avoid visually reinforcing separate daily bands.

## What links, colors, and sizes mean

Only `quotedPostId` and `parentId` produce 3D connection curves. Both endpoints must be present in the currently visible point set. Missing targets are not fabricated and are not automatically connected to the reference.

- Purple: quote references / posts with a quote reference.
- Teal: reply references / posts with a parent reference.
- Blue: other embedded posts.
- White: reference or active selection/hover styling.
- Gray: no usable saved semantic position.

A post with both reference types uses quote coloring for its glyph, while both recorded relationships can be drawn. Selected and reference styling can override relationship colors.

Curves are cubic Bézier drawing aids. Their deterministic bends are decorative, not intermediate events or inferred paths. The canvas does not draw directional arrowheads; the inspector identifies the direction with labels such as **quotes this**, **replies to this**, **quoted post**, and **parent post**.

Glyph size has a bounded, logarithmic contribution from captured likes, plus reference/selection emphasis and a minimum on-screen picking size. It is not an exact quantitative likes chart. Read the captured metric in the inspector instead. Missing likes do not acquire a displayed zero.

The 3D component does not use the older 2D story's semantic edges or backend hybrid ranking scores to position nodes.

## Missing features and source fidelity

The artifact includes model identity, method, creation time, source-file SHA-256 hashes, reference text hashes, basis identities, and per-post text hashes and features.

The browser accepts a layout only when the current reference text exactly matches its saved reference feature. It accepts a post feature only when that post's current text exactly matches the saved text under the same ID. It does not silently use a feature for a different text revision.

A post without a matching feature, or without a projected direction, retains its time position but goes onto a separate gray rail below the semantic display. This is a non-semantic placeholder, not zero distance from the reference. With no captured reference, the view waits rather than fabricating one.

The browser uses exact text matching, not full runtime verification of every stored file hash. The hashes support provenance and rebuild checks; they are not cryptographic authentication of public-source truth.

The inspector preserves captured source text and excerpt warnings. Source context may provide additional captured records or make a backend request when available. Missing reference targets are exposed as source links rather than fake graph nodes.

## Replay versus live retrieval

The Space play control is a **publication-time replay of currently supplied captured posts**:

- Posts are sorted by publication timestamp, with ID as a stable tie-breaker.
- A moving cutoff reveals posts whose timestamps are at or before the cutoff. Equal-time posts can appear together.
- Flow replay advances through the compressed Flow axis, skipping long clock gaps more quickly.
- Elapsed replay advances uniformly through elapsed time.
- The nominal full-span duration is 24 seconds at `1×`; `0.5×` and `2×` are also available.
- Scrubbing uses the same active transform and preserves real timestamps in the readout.
- A reference link appears only when both endpoints are visible.
- Pause stops this visual replay, not backend retrieval. Show all clears the replay cutoff but does not override the earlier-post filter.

This is separate from the outer recorded retrieval/event playback and from an actual live search. Discovery order may differ from publication order, and an older post can arrive late.

**The current 3D feature pipeline is saved-data only.** Newly retrieved posts can appear as records, but unseen texts do not acquire new MiniLM coordinates automatically. They remain on the unplaced rail unless a matching saved feature exists.

The backend separately has an optional Baseten embedding endpoint for ranking, configured with `SEQUITOR_BASETEN_EMBED_URL`, `SEQUITOR_BASETEN_EMBED_MODEL`, and a server-side credential. Its token-overlap fallback and hybrid ranking are not this saved MiniLM layout. Configuring that endpoint alone does not connect live semantic placement to Conversation Space.

## Rendering and implementation map

| File | Responsibility |
| --- | --- |
| `web/src/ConversationSpace.tsx` | Time transforms, cone scaling, Three.js scene, picking, inspector, replay |
| `web/src/conversation-space.css` | Responsive scene, toolbar, inspector, and playback styling |
| `web/src/Sequitor.tsx` | Active app, run state, canonical graph corpus, reference selection inputs, view integration, context modal |
| `web/src/sequitor.css` | Shared Sequitor layout and modal styling |
| `web/src/graphData.ts` | Shared graph post/reference types and older graph helpers |
| `web/src/Neighborhood.tsx` | Retained 2D alternative |
| `demo/recordings/build_conversation_space.py` | Local embedding inference and artifact generation |
| `demo/recordings/conversation-space.json` | Saved browser-consumable semantic features and provenance |
| `web/scripts/build-offline.mjs` | Standalone HTML packaging |
| `sequitor_server.py` | Existing local API, retrieval, ranking, events, and source-context support |
| `claimtrace/resolve.py` | Source resolution, including excerpt metadata |

Rendering uses direct Three.js, not React Three Fiber. Three.js and its types are pinned to `0.186.0` in the frontend dependencies. Nodes use an instanced mesh with stable post-ID lookup; curves use batched line segments. Rendering is demand-driven, with additional frames while controls, reveal animation, or camera transitions are active.

Points are not draggable away from their coordinates. Camera gestures do not rerun embeddings or fitting of the semantic basis. Reduced-motion preferences suppress entrance and camera-tween effects. Scene cleanup releases geometry, materials, textures, controls, observers, animation frames, and the WebGL context.

Initial renderer creation failure is handled. Full automatic recovery after a later WebGL context loss is not implemented. The HTML post list is an alternative, not a claim that the 3D canvas itself provides a complete keyboard graph-navigation system.

## Running and building

The inspected local toolchain uses Node `v24.13.0` and Python `3.12.12`. Saved browsing does not require model weights, Python numerical packages, or provider credentials.

### Frontend development

From the repository root:

```bash
cd web
npm ci
npm run dev
```

Vite serves the local frontend, normally at `http://127.0.0.1:5173`. It proxies `/api` to `http://127.0.0.1:8765`. Saved examples can be explored without live provider access. For local API-backed context and retrieval, start `python3 sequitor_server.py` from the repository root in another terminal. Live provider operations require separate valid configuration and may incur charges.

**Dependency portability caveat:** the current lockfile includes resolved URLs on `reposerver.w10external.com`, in addition to public npm URLs. A fresh `npm ci` outside that network may fail. It has not been validated from a clean public-only environment. The older browser README's claim that the whole lockfile is public should not be relied on for this revision.

### Production-style local build and server

```bash
cd web
npm ci
npm run build
cd ..
python3 sequitor_server.py
```

With the default port configuration, open `http://127.0.0.1:8765`.

### Portable saved-data HTML

```bash
cd web
npm run build:offline
```

Output: `web/dist/sequitor-offline.html`, relative to the repository root. Open it in a modern WebGL-capable browser. It embeds the JavaScript, styles, fonts, captured data, and semantic feature artifact. The packager currently requires a single JavaScript bundle; introducing dynamic chunks requires corresponding packaging changes.

Opening the saved Space needs no runtime model inference. This is **offline-capable**, not a guarantee that every part of the surrounding application never attempts a network request. External X links require connectivity, and other views or context integrations may attempt external resources or API requests. New live searches need the server and provider configuration.

### Regenerating saved semantic features — optional

Do not regenerate merely to run the browser; the feature artifact is already included. Regeneration rewrites that artifact, including its creation timestamp.

From the repository root, use an isolated environment under the ignored work directory:

```bash
python3 -m venv work/conversation-space/build-env
work/conversation-space/build-env/bin/python -m pip install numpy onnxruntime tokenizers
work/conversation-space/build-env/bin/python demo/recordings/build_conversation_space.py
```

After the required model files are cached, prohibit further model downloads with:

```bash
work/conversation-space/build-env/bin/python demo/recordings/build_conversation_space.py --offline
```

`--offline` prevents downloads; it can still compute missing embeddings using local weights. It fails if a required uncached model file would have to be downloaded. It does not substitute random vectors or TF-IDF.

Weights, full embedding vectors, basis caches, and the example build environment stay under ignored `work/conversation-space/`. The builder caches by model/input policy and text hashes. Python package versions are not fully locked here, so exact cross-environment numerical reproducibility is not guaranteed merely by pinning the model revision.

The lightweight feature artifact is intentionally included in source control; model weights, full vectors, dependencies, and generated `web/dist` output are not. No credentials belong in frontend configuration or the feature artifact.

## Related stabilization included in the pending work

The pending changes also include earlier Sequitor stabilization, not just the new 3D files:

- Essential feed content no longer relies on an entrance observer to become visible after tab changes.
- Native modal drawers support focus management, Escape, backdrop dismissal, and body-scroll restoration.
- Run, period, hourly, and context requests have separate lifecycle/stale-response protection.
- Incoming stream envelopes and terminal states receive defensive handling; cancellation preserves already received posts.
- Ranking labels, unknown-versus-zero counts, captured coverage, and immutable measured-query labels are kept distinct.
- Known excerpt metadata is propagated only for matching source IDs and text; text-only search inputs have no fabricated author or publication time.

These frontend and source-metadata improvements are **not** a public-live security hardening release. Shared authentication, account-wide spending controls, broader backend concurrency/cache concerns, and deployment safeguards remain outside this prototype. Do not infer that pushing this work makes the live API safe for unrestricted public exposure.

## Validation and release notes

The production build and standalone packaging passed after the Flow/cone changes. A brief browser walkthrough exercised mode switching and replay without page errors. This was intentionally limited validation, not a comprehensive new regression suite. The build still reports a large-bundle warning.

Current repository remote: `git@github.com:James-Begin/HTN2026.git`; current local branch: `main`. No commit or push was performed while preparing this document.

Before publishing, review the explicitly staged files, including the saved public-source text artifact. Do not force-add ignored model caches, generated builds, dependencies, or credentials. Commit and push authorization remains with the repository owner. A normal push should be allowed to reject a non-fast-forward update; do not force-push to bypass that check.
