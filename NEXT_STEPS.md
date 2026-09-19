# Product reset and next steps

## Status and governing direction

This plan responds to the latest user feedback and supersedes the earlier instruction to preserve the current editorial design. **This is a planning update, not implementation approval for all phases below.** No application code, source data, credentials, or deployment was changed while preparing it.

Repository: `/Users/james.begin/dev/claimtrace`. The current name, Claimtrace, is a working name pending a branding decision. **Git is now authorized for the user's requested upload to `https://github.com/James-Begin/HTN2026`.** Preserve the existing CLI, captured sources, and portable backup while developing the new experience.

## The product we should build

**Explore the conversation around a post: when attention grew, which posts became popular, and how people responded, joked, argued, and took it in new directions.**

The current demo overemphasizes corroboration, prominent authors, and an explanation written for the reader. That is not the desired product. The user wants to explore Twitter itself, not read an AI-authored report about it.

The core interaction should be:

> Open a post or topic → see its volume over time → select a period → read the most popular related posts → explore their surrounding conversation.

### What changes

- Authentic source records remain necessary; institutional credibility or celebrity status is **not** an inclusion requirement.
- Include ordinary accounts, jokes, memes, criticism, disagreement, replies, quotes, and tangents connected to the conversation.
- Same-claim scoring must not gate discovery or popularity. A joke can be highly relevant without restating the original claim.
- Popularity is not credibility, and semantic similarity is not evidence of copying.
- Existing source-tracing capabilities remain useful underneath the product, but should not dictate the default experience or its language.
- Intelligence can help with retrieval, query expansion, or grouping in the background. Generated narrative should not be the product's output.

## Product decisions and proposed defaults

### Volume

The left-hand chart should represent **all matching post activity within the declared conversation scope**, not the few posts displayed in the feed or the current hand-picked snapshot.

“All related posts” is a product goal, not a guarantee that an API exposes every discussion on X. Define a broad scope using the original post, wording variants, relevant links, and discoverable relationships. Measure the accessible matches to that scope and keep its definition inspectable.

Proposed default: volume includes related repost activity when supported. The popular feed presents distinct authored posts, including replies and quotes, rather than repeated native repost copies of the same original. Make this distinction available in the coverage details.

### Time navigation

- Add **Days / Months / Years**, with Days as the default for an unfolding conversation.
- Use an actual daily histogram rather than a list of selected-source counts.
- Hover/focus shows the date and matching-post count; click selects that exact interval.
- A selected month can be explored day by day; retain month/year overview navigation.
- Start with UTC throughout and display that timezone. Store inclusive start and exclusive end boundaries.
- Aggregate months and years from compatible daily data; missing intervals are unknown, not zero. Current/incomplete periods retain their coverage state.

### Period selection and popularity

- Selecting a day or month shows **up to the top 10 related posts published in that period**.
- Proposed ranking: captured likes, descending, with a stable tie-break. Do not introduce an unexplained composite virality score.
- This means likes observed at collection time on posts published in the period—not likes earned during that period. Historical engagement-by-day is a different dataset.
- Show fewer than 10 if fewer are available. Do not invent, duplicate, or pad results.
- Default to the selected period's top posts; provide a simple chronological alternative for following the conversation.
- Popularity must not use an author allowlist. Ordinary accounts and humorous offshoots compete by the same ranking rule.
- Retain the original post as accessible context without repeatedly duplicating it or confusing a pinned reference with the selected period's ranked results.

## Proposed minimal interface

**Recommendation: two persistent columns, with an optional context panel.** The previous three-column implementation duplicates the story and contributes to clutter; keeping it is not a requirement now.

```text
wordmark                         search

volume timeline     post feed
Days Months Years   selected period    Top / Chronological
                    X-style posts
                    ...

                    contextual drawer only when requested
```

- **Left:** compact volume chart and time navigation.
- **Main:** one feed of actual posts. Date selection changes its contents rather than merely dimming observations elsewhere.
- **Optional context:** the quoted/replied-to post, surrounding replies, or source details when opened. Not another permanent column of duplicate posts.
- On mobile, place a compact chart above the feed and use a sheet for context.
- Keep period changes stable: preserve the selected date, show factual loading state, reject stale responses, and avoid stealing scroll position as data arrives.

### Remove from the default experience

- Per-post generated/editorial headlines and explanatory paragraphs.
- The generated summary / “In context” essay and typewriter presentation.
- Claim-equivalence and credibility-style badges under posts.
- Marketing prose such as “Every claim has a backstory” and repeated methodological slogans.
- Large hero illustration, oversized introduction, repeated provenance footnotes, and stage narration.
- Always-visible methodology/CLI/export controls: move secondary actions into an unobtrusive menu.

**“No AI writing” means no app-authored interpretive prose in the experience. It does not mean modifying or hiding real posts that discuss AI.** Preserve their wording exactly. Short factual labels—dates, counts, loading/error status and coverage—remain appropriate.

Source coverage and snapshot/live identity still matter, but consolidate them into a compact indicator and an on-demand details view. Keep material limitations such as a truncated post visible where necessary.

### Post presentation

Render posts in a restrained, X-like form:

- Actual avatar, author name, handle and publication timestamp.
- Original text with its paragraph breaks and links.
- Quoted-post context and attached media when captured and available.
- Likes, reposts, replies, and other metrics only when actually supplied.
- Direct source link; no invented verification badge or replacement prose.

Use a local renderer rather than depending on live embedded widgets for the core experience. The offline fallback must still work without X scripts. Capture/cache required avatars and permitted media for the backup; use an honest placeholder when unavailable. Do not pretend this app is affiliated with X.

## Visual and naming direction

### Visual direction

- Neutral near-black background, charcoal surfaces, light text and muted neutral secondary text.
- Remove the current green/brown palette and mint-heavy accents.
- Use a consistent sans-serif family; retire the editorial serif headline treatment.
- Thin separators, restrained controls, simple spacing. Color should mostly come from the posts and their media, not the application's chrome.
- No decorative cards within cards, gradients, large slogan blocks, or animated narration.
- Subtle transitions only; retain keyboard access, contrast, responsive behavior and reduced-motion support.

### Names to explore

These are working suggestions, **not checked for domain, trademark, package, or product-name availability**.

| Name | Why it could fit | Design trade-off |
|---|---|---|
| **Offshoot** | Captures a post branching into jokes, arguments and new conversations. | Strong fit for exploration; less explicitly about time. |
| **Wake** | Short, minimal; the trail a post leaves behind. | Memorable but ambiguous without a descriptor. |
| **Ripple** | Immediately suggests spread and attention. | Needs a particularly careful collision check. |
| **Relay** | Emphasizes sharing and passing things along. | Less expressive about mutation and offshoots. |
| **Threadline** | Suggests following a conversation through time. | More descriptive, less minimal. |
| **Afterpost** | Focuses on what happens after the original post. | Distinctive concept, but the coined word needs a visual trial. |

**Recommendation:** explore Offshoot and Wake as wordmarks on the same monochrome layout before choosing. Do not rename the repository, packages, CLI commands, or files yet.

## Implementation sequence

### Phase A — align the product and visual prototype

1. Agree on the conversation-exploration framing, the default likes ranking, and the two-column layout with optional context.
2. Produce a minimal visual pass using existing real posts, without implying that the current sample is a volume dataset.
3. Remove per-post headlines, annotation paragraphs, summaries, and promotional prose from the normal UI.
4. Show the shortlisted wordmarks in the proposed dark theme. Choose a name before applying a repository-wide brand change.

**Exit:** the feed and timeline feel like a polished product even without a narrative explaining them.

### Phase B — define the data contracts

Extend the event-driven foundation rather than replace it:

- `ConversationScope`: root/seed references, canonical query or discovery definition, version, requested window, language and post-type policies.
- `Period`: day/month/year and exact UTC boundaries.
- `VolumeBucket`: interval, count or null, covered interval, coverage and measurement time.
- `PeriodPostsResult`: scope/version, exact interval, ranking metric, ordered post IDs, candidate coverage, capture times and any truncation reason.
- Source metadata: author identity/avatar, full or explicitly truncated text, public metrics, media, conversation ID and typed references.

Keep **volume coverage and ranking coverage separate**. A complete count does not mean we downloaded enough posts to determine the top ten.

Period selection after an initial run completes is a new request lifecycle. Add a dedicated period-results state/controller with request IDs, caching, cancellation and stale-response rejection; do not weaken the existing investigation reducer's terminal guards.

### Phase C — collect broad measured data for the frontier example

1. Confirm X search/counts access and agree on a bounded collection budget and window around the launch, with a pre-launch baseline. No credentials were configured during the previous source-snapshot collection; recheck safely before proceeding.
2. Discover across title/phrase variants, relevant URLs, replies, quotes and branches—not just posts by prominent people.
3. Locate the user's remembered **“Gemini has been pacing the frontier for years”** joke using wording variants and surrounding conversations. Exact wording, author, URL and engagement are currently unverified. Do not recreate it from memory.
4. Include humor and criticism in the captured corpus. The remembered joke should remain discoverable even if it does not qualify for a particular period's top ten; do not force it into a falsely ranked list.
5. Collect daily counts for the agreed scope, with complete pagination and explicit coverage metadata.
6. Retain raw responses, retrieval queries, timestamps and IDs so the dataset can be audited and replayed.
7. Obtain fuller post text and media where access permits; otherwise preserve clear excerpt/missing-media states.

**Important retrieval distinction:** a quote post may say only “Dario is right,” without containing the original phrase. Keyword search alone will miss this class of response. Use supported quote/reply/conversation traversal with a bounded frontier and visited-ID deduplication. Verify operator/endpoint availability before relying on it.

**Scope consistency:** do not add overlapping phrase-query totals together. Prefer one supported union query or provably disjoint partitions. Aggregate counts cannot be deduplicated by post ID after the fact. If relationship discovery adds posts outside the countable scope, either revise and remeasure that scope or explicitly retain separate/incomplete coverage—never quietly add a branch sample to a complete volume total.

**Exit:** the chart measures a broad defined conversation, while the corpus includes organic viral offshoots beyond the original executive reactions.

### Phase D — implement reliable period rankings

1. Retrieve candidates within the selected day/month boundaries and deduplicate canonical post IDs.
2. Rank by captured likes; preserve unknown metrics rather than treating them as zero.
3. Use complete candidate retrieval or another coverage-verifiable method to establish the requested ranking. Check paid access, pagination and budget behavior before scaling collection.
4. If collection is capped, label results as top **retrieved** posts, not the definitive top ten. This can differ from a fully measured volume chart.
5. Cache by scope/version, period, post-type policy, metric and capture version. Avoid repeated paid work when revisiting a date.
6. Prepare offline rankings for the backed-up date range, without making period clicks depend on a live API.

The search documentation inspected exposes recency/relevancy ordering, not a likes sort. Sorting one newest-results page cannot establish the most popular posts in a period. Existing `cascade()` must not be reused as though it does.

For monthly rankings, use the retained candidate corpus by default. A union of daily top-ten lists is sufficient only when every day is covered completely, the metric snapshots are consistent, and the ranking/tie-break rules match; incomplete or differently captured daily caches do not establish a monthly ranking.

**Exit:** date clicks predictably show up to ten posts from that period with a defensible ranking and no stale cross-period results.

### Phase E — package and validate the stronger fallback

- Build the new dataset into the same no-network fallback mechanism.
- Preserve old captures as source history rather than relabelling the existing small sample as complete volume.
- Bundle the agreed date range's daily counts, rankings, source posts, and available media.
- Validate daily/monthly aggregation, overlapping queries, UTC boundaries, missing metrics, request races and pagination truncation using local/ad-hoc checks first.
- Recheck source fidelity, keyboard/mobile interactions, accessibility and offline startup with the network disabled.
- A reviewer should be able to select a spike, read its popular posts, and discover a funny or unexpected offshoot without reading generated explanations.

**Exit:** the demo is compelling as an exploration tool, and the portable backup contains enough data to support its visible interactions honestly.

### Later — an interactive spread graph

Treat this as an alternate view once the feed/timeline are strong, not another permanent panel now.

- Save post/author IDs, publication times, quote/reply/repost references and discovery provenance from the next collection onward.
- Begin with observed relationships and time filtering; open the actual post from a node.
- Distinguish explicit references from any later similarity-based links. An unlinked joke can be related without a proven parent.
- Do not interpret chronology or text similarity as evidence that somebody saw or copied a particular post.
- “Different parts of Twitter” needs sufficient interaction data and a defensible grouping method. Do not invent community labels or imply access to private exposure/impression pathways.

## Existing foundations to retain

- React/TypeScript/Vite frontend and the shared normalized event reducer.
- Stable-ID source updates, source-link helpers, capture metadata, keyboard and responsive foundations.
- Existing Python CLI behavior while the new conversation-oriented browser flow is developed separately.
- Saved X source data and raw capture hashes.
- Portable single-file backup generation. External source links require internet, but the built replay does not.

The composer/typewriter component need not remain in the user-facing flow. When connecting a backend, avoid paying to generate prose that the product no longer displays. Do not redeploy or retrain a model just to support this redesigned demo.

## Current implementation locations

- `web/src/App.tsx`: landing/navigation, example entry points, branding and export.
- `web/src/Investigation.tsx`: replace the editorial chronology/duplicate-post arrangement with the feed/context layout.
- `web/src/Timeline.tsx`, `web/src/timeline.css`: daily resolution, histogram and period selection.
- `web/src/investigation-state.ts`: scopes, periods, richer source data and coverage; preserve terminal semantics.
- `web/src/Dialog.tsx`, `web/src/evidence.ts`: source presentation and on-demand details.
- `web/src/styles.css`, `web/src/investigation.css`: neutral dark redesign.
- `web/src/frontier-recording.ts`: existing small saved-source adapter, not broad conversation coverage.
- `web/src/StreamText.tsx`: current generated-text presentation; remove from the normal experience rather than expand it.
- `claimtrace/xapi.py`: search/counts pagination, structured queries, coverage and relationship retrieval need review. Existing `daily_curve()` ignores continuation and `counts_total()` has a page cap without adequate coverage reporting.
- `demo/recordings/pace-the-frontier/`: current source snapshot, raw responses and collector. The embed-only collector cannot measure total conversation volume.
- `web/scripts/build-offline.mjs`: portable backup packaging; update as needed for cached media while preserving network-free startup.

## Run and backup commands

```bash
cd /Users/james.begin/dev/claimtrace/web
npm run dev
npm run build:offline
```

The generated backup is `web/dist/claimtrace-offline.html` relative to the project root. A later build clears `dist`; copy presentation backups somewhere safe. No broad volume dataset or daily top-ten feature has been implemented yet.

## Deferred operations and constraints

- The user authorized repository setup and pushing relevant code to `James-Begin/HTN2026`. Exclude secrets, dependencies, bulk datasets, model weights and generated builds.
- No credential changes, paid collection, model redeployment, or Railway resource changes as part of this planning task.
- Keep secrets server-side. Confirm budget and access before the richer collection; never ask for shared tokens to be committed to files or frontend variables.
- Existing backend lifecycle, cancellation and spend-control work remains necessary before live execution, but is no longer the immediate visual/product priority.
- Railway hosting and Baseten remain deferred. Verify current deployment status and replace the previously chat-exposed Railway credential securely before any authorized deployment; do not reproduce its value.
- Do not add test files or expand into unrelated repositories without approval.

## Decisions to make next

1. Choose a naming direction—recommended visual trials: **Offshoot** and **Wake**.
2. Confirm the simpler timeline + single-feed layout and likes-based top-ten default.
3. Approve the next implementation slice: the neutral-dark, post-first visual redesign and daily/period data contracts. Richer X collection follows once access and a budget are agreed.
