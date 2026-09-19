# Live pipeline investigation — Claude Code

**Date:** 2026-09-19  
**Status:** completed once against the live provider path  
**Seed:** `Claude Code is changing how developers build software.`

## Boundary

This was one deliberately bounded live run. It used one X count request and 60 additional X post reads, taking the existing ledger from 539 reads / $2.705 estimated spend to 599 reads / $3.015. It did not start a second run. The raw API event snapshot, run identifier, and other provider-returned material are stored only in ignored `work/live-tests/2026-09-19-claude-code/`.

## What ran

| Stage | Result |
| --- | --- |
| Seed resolution | Text seed accepted; no source-post lookup was needed. |
| OpenAI context plan | Completed with `gpt-4.1-mini-2025-04-14`; it generated two discovery branches: `Claude Code` and `Claude programming`. |
| X phrase activity | Completed with 15 daily buckets; selected day was 2026-09-10. |
| Primary retrieval | Two phrase-match posts returned. |
| Discovery retrieval | 57 broader-discovery posts returned. |
| Grounded context expansion | Completed but correctly produced no extra query for this evidence set. |
| Baseten curation | Hosted `openai/gpt-oss-120b` curated 3 posts. |
| Retrieval scoring | Every returned post received a score, but semantic ranking used the explicit `token-overlap fallback`; no embeddings endpoint or trained reranker endpoint is configured yet. |
| SSE completion | 44 events, from `run.started` to `run.completed`, in about 12 seconds. |

## Findings

1. **The live pipeline completes and preserves provenance.** The stream included the plan, 15 activity updates, retrieved-post updates, the expansion decision, model-ready state, and completion. It produced 59 deduplicated posts: 2 measured-phrase and 57 broader-discovery.

2. **The activity phrase drifted away from the named subject.** The planner selected `"changing how developers build software"` as the exact measured phrase instead of a phrase containing `Claude Code`. That is too generic for the chart and makes the bar data less interpretable, even though the separate discovery queries retained the subject. Require a named entity or distinctive product phrase in the volume phrase when the seed supplies one, with a deterministic fallback to the entity phrase.

3. **SSE delivery still explains the visible chunking.** The first retrieval paced individual posts about 116 ms apart. Later updates were emitted in groups of 10–24 with intervals as low as 0–33 ms; the curation stage emitted five 12-post groups in the same millisecond. A browser cannot visibly animate those as a stream. Pace every `posts.upsert` batch, including the post-curation re-emission, and make the frontend animate its receive queue independently of network event timing.

4. **The test exercised fallback ranking, not the intended semantic stack.** The result correctly identifies `token-overlap fallback` and `awaiting trained endpoint`. Configure the Baseten embedding route and the separately trained reranker before presenting semantic ranking as live-model behavior.

5. **The current UI cannot attach to an already-completed job by run ID.** The completed local page loaded the recorded Dario capture. This is expected for the present UI flow, but it prevents a post-run browser inspection of a job launched through the API. The normal `Explore live` interaction will be the end-to-end UI check once the X post budget is refreshed.

## Saved evidence

- Ignored raw event snapshot: `work/live-tests/2026-09-19-claude-code/events-snapshot.json`
- Ignored run id: `work/live-tests/2026-09-19-claude-code/run-id.txt`
- Durable server event log: `work/sequitor-streams/0dbbcb8039d648f786581e8ef14bd787.jsonl`

The tracked report intentionally excludes retrieved post text and identifiers so the repository does not publish paid API data.
