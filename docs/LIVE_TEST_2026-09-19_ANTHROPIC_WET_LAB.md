# Live investigation — Anthropic Wet Lab

**Date:** 2026-09-19
**Seed:** `Anthropic is opening a wet lab`
**Status:** completed, then followed by one narrow corrective count and retrieval

The first live run completed OpenAI planning, X counts, two discovery queries, one evidence-based expansion query, Baseten hosted curation, and SSE. It retrieved 52 posts and moved the X ledger from $3.015 to $3.305. The model chose the exact chart phrase `"Anthropic is opening a wet lab"`, which had **zero** X matches in the two-week window. The app incorrectly selected September 5 as a peak anyway and showed 52 mostly broad Anthropic/lab/hardware posts. This was a failed retrieval result, despite the pipeline completing technically.

A targeted context count for `Anthropic wet lab` found 2,260 matches on September 18 and 1,175 on September 19. A single September 18 search returned 19 recent posts and indicated more pages were available. Those posts include an [explicit wet-lab reference](https://x.com/i/status/2101098368500179035), [a skeptical reaction](https://x.com/i/status/2101091531054547076), and [a question about lab regulation](https://x.com/i/status/2101095308633739740). These are source posts about the discussion, not independent verification that Anthropic opened a lab. The targeted result is saved as the **View Anthropic Wet Lab test** example in the app. It is a recent slice, not a representative or complete sample of 2,260 posts.

The server now uses a clearly labelled, grounded context-count query when the literal phrase has zero activity. If both counts are zero, it stops instead of fabricating a peak. The saved example uses the observed targeted counts and source posts; it does not claim Baseten reranking was run on those 19 posts.

The corrective count and retrieval added about $0.105 of estimated X spend. A separate three-result humor search for the Dario investigation also ran; the persistent local ledger ended at **680 post reads, 4 counts calls, $3.44 estimated total**. Raw test responses are kept only in ignored `work/live-tests/2026-09-19-anthropic-wet-lab/`.

Next check: after the branch-search work in [SEARCH_BRANCH_PLAN.md](SEARCH_BRANCH_PLAN.md), run one bounded Wet Lab query through the revised frontend and confirm that the default day lands on actual September 18–19 discussion, with announcement, commentary, and humor represented and unrelated “Anthropic lab” results removed from the first screen.
