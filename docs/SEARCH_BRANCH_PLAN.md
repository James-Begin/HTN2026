# Sequitor search branches — next build plan

## Why this change

The Dario capture missed “who up pacing they frontier” because the current feed searches a literal phrase and a small set of serious context queries on one selected day. A targeted X search for `"who up pacing they frontier"` found three public posts: one on September 12, roughly ten minutes after Dario's starting post, and two on September 13–14. They express a response to the event without restating the seed's claim. Semantic ranking cannot surface a post that retrieval never fetched.

The “Anthropic is opening a wet lab” live test exposed the complementary failure: the exact seed sentence had zero activity, yet the app chose the first zero-count day and fetched 52 mostly unrelated results from broad queries. A targeted count for the grounded query `Anthropic wet lab` found a substantial September 18–19 discussion. A zero-count phrase now triggers that explicit context-count fallback, but branch design still needs refinement.

## Retrieval design

1. **Make an event card.** OpenAI extracts named entities, action, object, distinctive phrases, aliases, date/window, and what is uncertain. Keep each field tied to the seed text or a retrieved post. Use it to describe the investigation, never as proof that the event occurred.
2. **Create separate search paths.** Give every query a purpose and budget:

   | Path | Candidate query shape | What it should find |
   | --- | --- | --- |
   | Announcement | Quoted distinctive phrase, original account, direct quote/reply references | The seed and direct amplification |
   | Reporting | Entity + event object or action | Straight summaries and follow-up facts |
   | Commentary | Entity/event + consequence, policy, or objection term seen in evidence | Analysis, criticism, and questions |
   | Humor | Morphological variants and short cultural rewrites of distinctive terms, e.g. `pacing frontier` | Jokes, memes, and playful paraphrases |
   | Wider context | New entity or phrase appearing in several already retrieved posts | Adjacent discussion that is genuinely connected |

3. **Use counts to allocate reads.** Check activity for each proposed query before fetching posts. Spend a small fixed read budget per viable path and day; reserve some reads for low-engagement humor. Skip branches with no activity or excessive broadness. Search the seed day and a few later windows rather than only the global peak day. Record every query, time window, count, truncation flag, and number of fetched posts.
4. **Expand once from evidence.** After first-pass retrieval, OpenAI may propose at most two missing search paths, grounded in quoted snippets of current results. A query only runs if it adds a new entity, phrasing, or genre. No unbounded recursion.
5. **Rank within and across paths.** Deduplicate posts by ID, then score relation to the *event card*, observed reply/quote links, lexical and embedding similarity, and path-specific cues. The trained same-claim reranker should help the reporting path; it must not suppress jokes merely because they do not assert the seed's claim. Return a diverse feed with a visible path label and a concise “why included” explanation.
6. **Keep chart provenance honest.** A literal-phrase chart is labelled as such. If it has zero matches, show the distinct context query actually counted. Never call an arbitrary zero day the peak. If all grounded queries have zero counts, show a no-evidence state rather than unrelated posts.

## First implementation slice

- Add typed query proposals to the OpenAI search plan (`path`, `query`, `evidence`, `why`). Keep one or two candidates per path.
- Count and retrieve with a total per-investigation cap; return branch coverage in SSE and the saved run.
- Add path chips and filters to the feed; make one humorous result visible in the Dario example without presenting it as a Baseten classification.
- Use the captured Dario and Wet Lab runs as regression examples. Success means the September 12 humor post appears and the Wet Lab default day shows posts from the actual September 18–19 activity, with no unrelated “Anthropic lab” results among the first screen.

## Spend and evaluation

Prototype against saved responses first. Then run one live test per change, logging provider stages, X reads, counts calls, estimated spend, recall of known posts, and a small manual precision check across all paths. Keep the existing server cap and stop when the available credit margin is too small for a useful run.
