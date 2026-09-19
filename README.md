# claimtrace

Paste a claim or a tweet URL. Get either its lineage back through the archive, or
an honest read on whether anyone actually corroborates it.

```
python cli.py "some claim text"
python cli.py --url https://x.com/user/status/2099253016847090149
python cli.py "claim" --mode lineage --budget 400 --min-likes 2000
```

Needs `X_BEARER` and `BASETEN_API_KEY` in the environment. See `.env.example`.

---

## What it does

```
resolve -> extract -> shape -> route -> (verify | lineage) -> judge -> compose
```

**shape** is the router, not a report. One flat-rate counts call returns a 30-day
daily curve, and the shape of that curve decides everything downstream:

| Curve | Route | Cost | Wall |
|---|---|---|---|
| Flat, then a spike in the last 3 days | `VERIFY` | ~$0.09 | ~14s |
| Long background, then a spike | `LINEAGE` | ~$0.19 | ~66s |
| Nothing at all | `ABSTAIN` | $0.01 | ~1s |

**verify** tests for *expected corroboration absence*. It never says true or false.
It reports raw volume, verified-author share, originals-versus-retweets, optional
authority-list volume, whether the subject has said anything, and **each premise
measured separately** — because a false claim will happily attach itself to a real
adjacent event.

**lineage** bisects on existence to find the earliest matching post, then shows a
like-thresholded cascade rather than a full timeline. 36,000 posts is noise; the
ten above a threshold are the story.

**judge** is a dedicated cross-encoder on Baseten that scores every candidate for
same-claim probability. It is what separates a real instance from a string match.

---

## Measured results

Two real runs, both reproducible.

**Verify** — a claim about SSI being delayed, two hours old:

```
raw 7d                    30
verified authors          19   63.3%
originals (no RT)          3   10.0%
retweet share          90.0%
premise vol               28   ssi are delayed after a catastrophic security incident
premise vol              160   the incident was discovered after seeing what happened with openai
premise vol               25   order of magnitude more damage caused
```

The adjacent premise carries **160** against the claim's **28**. The claim is
borrowing credibility from a real event, and the numbers surface it without being
told to look.

**Lineage** — Dario Amodei's "We Must Pace the Frontier":

```
30d volume    16,679   peak 9,571 on 2026-09-12   spike ratio 9,571x
earliest      2026-08-12T02:47:48Z  id=2087370436959186977
              '"ceterum censeo we must pace the frontier of global machine intelligence progress"'
              likes=247  rt=9
probes        30
```

The earliest instance predates the famous essay by **a month**, and the
cross-encoder scores it 0.4053 — related, but not the same claim. That three-way
split between first occurrence, definitional use, and amplifier is the whole point.

---

## Facts this code encodes

Everything below was measured against the live APIs. None of it is inferred.

### X API

- **Full-archive search works on pay-per-use** and genuinely reaches March 2006.
- **Billing is per row returned, so a probe that misses is FREE.** This is what
  makes existence-bisection cheap near an origin.
- **Counts are flat-rate** per request regardless of volume. Use them for anything
  volumetric, and as a free density check before paying to enumerate.
- `meta.total_tweet_count` is **per-page only**. It cannot shortcut a range sum.
- Counts pages are 31 wall-clock days, **newest first, paging backwards**.
- Search returns **newest-first and truncates hard**. A dense window can never be
  read directly; keep bisecting instead.
- `max_results` floor is **10**, ceiling 500. Passing 1 returns HTTP 400.
- `end_time` cannot be the present moment.
- Engagement operators are **`min_likes` / `min_reposts`**. The web-search names
  `min_faves` / `min_retweets` are rejected outright.
- **X uses implicit AND.** The literal token `AND` is not an operator; a space is.
  `OR` is valid. This breaks model-generated queries constantly.
- Rate limit is **300 requests / 15 min per app** and money does not move it.
  Multiple apps for one use case is a policy violation.
- The usage meter **lags**, so local counting must be authoritative.
- Semantic search exists as `embedding:` but is Enterprise-plus-add-on **and
  Filtered-Stream only**, so it points forward in time. Useless for lineage.

### Baseten

- **Hosted Model APIs cap at 120 requests/minute** (`X-Ratelimit-Limit-Requests`).
  Fine for a few calls per query. Useless for bulk. Concurrency 8 is healthy;
  64 collapses throughput to 1.4 req/s.
- **A dedicated L4 cross-encoder does 2,851 pairs/sec**, 88ms p50 for 32 pairs,
  no shared cap. That ~1400x gap is why the dedicated deployment is load-bearing.
- **`reasoning_effort: "none"` works.** `chat_template_args={"enable_thinking": False}`
  does nothing. Left at default, these models burn 68-89 reasoning tokens on a
  one-word answer.
- Too tight a `max_tokens` returns `content: None` with `finish_reason: length`,
  **silently**. Always leave headroom.
- Measured latency at `effort=none`: `inkling-small` 167ms / 156ms TTFT,
  `gpt-oss-120b` 237ms / 227 tok/s, `GLM-5.3-Fast` 1256ms despite the name.
  `DeepSeek-V4-Flash` was fast but answered our real task **wrong**.
- A sequence-classification model **does** serve on their embeddings engine via
  `base_model: encoder_bert` + `webserver_default_route: /rerank`, despite there
  being no worked example in the docs. Build took ~4 minutes, not 10-20.
- **A payment method is required to deploy anything**, even with credits on file.
- **Training capacity starts at zero.** `GET /v1/training/capacity` returning
  empty means a `train push` will queue forever with no error.

---

## Known gaps

- **The composer can hallucinate.** One run invented a corporate commitment that
  was not in the evidence. A groundedness classifier over each output sentence is
  the obvious next component, and it is not built.
- **The fine-tune is DEPLOYED and wired in.** Model `q9p28o63` on one L4, serving
  faithfully: across all 205 hand-labelled pairs the deployed fp16 scores differ from
  local fp32 by at most 0.0032 and **no pair crosses the accept threshold differently**.
  Throughput is 434 pairs/sec against 2,851 for the off-the-shelf reranker on TensorRT,
  which is affordable because a run scores ~50 pairs in 0.12s inside a 14-66s wall time
  dominated by the X API. See `deploy/README.md`.
- **The gate now uses two thresholds, not one.** Accept at 0.70, reject below 0.32,
  abstain between. A false accept is the expensive error because verify mode counts
  corroborating posts. The abstain band catches `ssi-05`, the acronym collision that a
  single cutoff got wrong either way.
- **The fine-tune helped, but about half the headline gain was the base-model swap.**
  On the blind 180-pair holdout, AUC went 0.823 for the served model, to 0.864 for the
  untrained larger base, to 0.916 fine-tuned. So +0.041 of the +0.093 gain was a model
  choice, not training. Training's clear win is `meta` suppression: both untrained models
  score some commentary above 0.94, where a denial would be counted as corroboration, and
  the fine-tune caps `meta` at 0.628. Calibration also halved, Brier 0.281 to 0.139.
- **The paraphrase gap is narrower but still open.** The off-the-shelf cross-encoder had a separation
  margin of -0.80, meaning no threshold classified the eval set correctly. The
  fine-tune in `runs/xenc-best` passes the release gate: 4 of 4 unlock gates, 7 of 7
  regressions held, margin +0.0056, ROC AUC 1.000, calibration error 0.0987. It is not
  yet DEPLOYED to Baseten. See `train/README.md`.
- **The 25-pair gate was overstating performance, and a 180-pair blind-labelled
  holdout proved it.** On the larger set ROC AUC is 0.916 rather than 1.000, F1 at the
  default threshold is 0.78 rather than 0.90, and **32 of 80 genuine paraphrases still
  score below 0.5**. The paraphrase gap is much narrower than the served model's but not
  closed. See `eval/README.md`.
- **The accept threshold should be near 0.32, not 0.5.** Three independent estimates now
  agree it belongs below 0.5: English validation 0.399, mixed-language validation 0.253,
  and the holdout's best F1 at 0.319.
- **The pipeline labeller gets `meta` right 11 times in 21** and calls 8 of them
  `same_paraphrase`, which is the direction that makes a verify run report the opposite
  of the truth. The 1,436 `meta` training rows are contaminated accordingly.
- **X only.** Bluesky, the Reddit archive mirror, and the Wayback index are all
  free and unimplemented. The origin of a viral tweet is usually not a tweet.
- **No local corpus.** Every run hits the network, so nothing is cached and the
  demo depends on connectivity.
- **The bisect takes ~63s** for 30 probes, dominated by the 1/sec throttle.
- **Extraction is non-deterministic.** The anchor drifted between identical runs.

## Tests

```
python -m unittest discover -s tests -t .                   # 231 tests, ~28s, ~$0.15
CLAIMTRACE_SLOW=1 python -m unittest discover -s tests -t .  # +3 bisects, ~$1.20
python -m unittest discover -s tests -t . -p 'test_[uem]*.py'  # 192 offline, 2.1s, $0
```

| Suite | Tests | Network | Cost |
|---|---|---|---|
| `test_units.py` | 39 | none | $0 |
| `test_eval.py` | 50 | none | $0 |
| `test_mine.py` | 69 | none | $0 |
| `test_train.py` | 34 | none | $0 |
| `test_resolve.py` | 19 | free, keyless | $0 |
| `test_integration.py` | 20 | X + Baseten | $0.15 / $1.20 |

Assertions live in `tests/fixtures/`. `cases.json` records what was measured on the
live APIs; `corpus.json` holds 45 independently verified tweets spanning 2006-2026
with **zero fabricated ids**.

One test is designed to fail. `test_paraphrase_gap_is_still_open` asserts the
paraphrase score stays *below* threshold. When the fine-tune lands and it starts
failing, that is the signal it worked.

### Two bugs the tests found

**The router.** A failing test looked like a router bug. It was not.

| Query | Pre-spike posts | Correct route |
|---|---|---|
| `"We Must Pace the Frontier"` (title) | 3 | VERIFY |
| `"pace the frontier"` (phrase) | 16,664 | LINEAGE |

The essay title has three scattered singletons in a month, so there is no history
to trace. The phrase inside it has a ramp of 4/14/37/76/59. Same event, two
queries, two correct answers. Routing therefore keys on **pre-spike volume**, not
on whether the spike is recent.

**The fixture.** A recorded similarity of 0.1332 measured as 0.2880. Both correct:
the first was scored against a short query, the second against the full claim. A
cross-encoder score is a function of *both* texts, so a fixture must record which
query produced it.

---

## Snowflake decoding and the four-state resolver

A tweet id carries its own timestamp: `(id >> 22) + 1288834974657`. Free, offline,
and it **works on deleted posts**. Ids below `29700859904` predate Snowflake and
raise rather than return a plausible lie.

The keyless syndication endpoint distinguishes four states, which is strictly more
useful than pass/fail:

| Response | State | Meaning |
|---|---|---|
| `__typename: "Tweet"` | `LIVE` | full text, handle, media |
| tombstone, "deleted by the Post author" | `DELETED` | **id real, content gone** |
| tombstone, "limits who can view" | `PROTECTED` | id real, account locked |
| tombstone, empty | `GONE` | account removed |
| HTTP 400 or 404 | `NONEXISTENT` | fabricated id |

`DELETED` is a **positive finding**, and it is the case this tool exists for. The
covfefe original, id `869766994899468288`, decodes to `2017-05-31T04:06:25.730Z`.
Our bisect found the earliest survivor at `04:06:26Z` — a gap of **0.27 seconds**
on a post deleted nine years ago.

### Three edge cases now guarded

- **The most-liked tweet in history has no prose.** Id `1299530165463199747`, 6.65M
  likes, and its text is a bare link with the claim in two attached images. A
  text-only pipeline scores it as a null document, so the CLI refuses and says why.
- **Handles drift.** Id `14599635273` was `@BPGlobalPR` and is now `@thededsouls`,
  so every published citation points at a dead handle while the id still resolves.
  Identity keys on `author_id`, never the screen name.
- **A deleted root sits next to a live follow-up.** The covfefe original and its
  surviving sequel are six hours and one topic apart. Retrieval will happily return
  the survivor as if it were the origin. That is the failure mode to catch.

### Retrieval-hostile corpus

Posts that keyword search structurally cannot reach: `@dril` posting the single
word "no" with 122k likes; `@jack` posting "lunch"; Elon posting a lone
**U+1D54F** which is not ASCII `X`; "Everything happens so much", an ordinary
English sentence. And two where a **typo is a better fingerprint than the
sentence**, because reposters preserve "scraeming" and "aboutr" verbatim.

### Premises corrected during research

The world record egg was an Instagram post. "It's Wednesday my dudes" started on
Tumblr. "Bones day" started on TikTok. "Deez nuts" predates Twitter. None has an
originating tweet, so none is tested. Four further cases were left without ids
rather than guessed at, including the 2013 AP hack tweet, after 2,462 archived ids
were checked and none fell in the window.

---

## The terminal frontend

The CLI is a thin consumer of an event stream, not the app. `claimtrace/events.py`
defines the contract, `claimtrace/render.py` draws it, and `--json` emits the same
events as NDJSON, which is the wire format a browser will read over SSE unchanged.
One source of behaviour, two renderers.

**The bisect is the centrepiece.** Thirty probes collapsing twenty years of archive
down to a second, drawn as a staircase so the whole search stays visible:

```
  01 c ███████████████████████████████████████████· HIT   20.5y
  02 c ·····················██████████████████████· miss  10.2y
  03 c ································███████████· miss   5.1y
     ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ zoom 1.3y
  06 c ···········██████████████████████···········  HIT   234d
```

The axis auto-zooms, because at full scale the window is sub-pixel after six
probes. Getting the padding right took two attempts: a *multiple* of the window
re-zooms on every probe, a *fraction* of it survives about four halvings.

Also drawn: a five-row bar chart of the 30-day curve, horizontal bars for the
corroboration ratios, accept marks on cross-encoder scores, and one deliberately
loud **headline** panel carrying the single number that matters for that run,
chosen per run rather than from a template.

## Layout

```
cli.py                  entrypoint, rendering, stage timing
claimtrace/config.py    every measured constant, with provenance
claimtrace/xapi.py      rate governor, spend guard, bisect, query sanitizer
claimtrace/baseten.py   hosted LLM + dedicated cross-encoder
claimtrace/resolve.py   four-state keyless resolution
claimtrace/pipeline.py  extract, shape, route, verify, lineage, judge, compose
eval/                   claim-equivalence eval set + release gates
mine/                   real training pairs harvested from Bluesky, free
train/                  the fine-tune, sweep, and threshold calibration
deploy/xenc/            the custom Truss actually serving the model
runs/xenc-best          the shippable checkpoint
tests/                  231 tests + verified fixtures
```

## Training data: mined, not generated

`mine/` harvests claim pairs from 34 Bluesky outlet feeds across 8 languages.
Keyless, free, and no GPU. The rule is that the model **labels real text and never
writes text**: real text keeps the distribution honest, and the only error introduced
is label noise, which is measurable, where generation introduces distribution error,
which is not.

The join key is a shared event, not a shared link. Outlets link their own article and
Reuters shortens to `reut.rs`, so two outlets covering one event share no URL at all.
Rare-token overlap in a narrow time window works instead, because independent
newsrooms reuse the proper nouns and the numbers and little else.

This buys two things generation cannot. Real cross-lingual pairs, such as an English
and a French report of one plane crash at Jaccard 0.069, which is the shape of the
worst measured failure. And same-topic-different-claim hard negatives, such as a
match preview against that match's result, which sit at the same lexical overlap as a
true paraphrase and so cannot be separated by any heuristic.

Two things drive yield and neither is more pages of the same feeds. Candidates come
from cross-outlet pairs, so outlet count matters quadratically. And pairs only form
where outlets cover the same days, so every outlet is paged to a common floor date
rather than a common page count. Getting that wrong wasted a whole scale-up: tripling
the corpus raised candidates by only 41%, because the extra pages landed outside the
intersection.

| | Outlets | Posts | Candidates | Cross-lingual |
|---|---|---|---|---|
| flat page count | 9 | 13,412 | 2,673 | 1,156 |
| common floor, 45 days | 34 | 59,580 | 9,874 | 4,415 |

Crossing a script boundary needs a translation bridge, because the join runs on
shared tokens and Al Jazeera Arabic carried Latin tokens in 0 of 25 posts. Each
non-Latin post gets one English translation used **only to compute the join**; the
stored pair keeps the original text, and language detection reads the original so a
Japanese post stays Japanese. Validated on 141 English-Japanese pairs.

The labeller had to earn the job and is gated on agreement with the hand labels. See
`mine/README.md`, including why a single validation round on 21 pairs is not a
measurement, and why no active Arabic outlet exists on Bluesky to source the case
that motivated the bridge.

## The fine-tune

`train/` fine-tunes a 5-class cross-encoder on 8 local A10Gs and scores every
checkpoint on the release gate. The result passes: **4 of 4 unlock gates, 7 of 7
regressions held**, ROC AUC 1.000 against 0.771 for the served model.

Two findings shaped it. First, the two gate failures on the first checkpoint traced
straight back to the two cases the labeller itself gets wrong, so label noise
propagated into the model; both were fixed with free structural data targeting the
exact shape. Second, training English-only produced a model that separated English
cleanly and cross-lingual not at all, so it wanted two different thresholds and could
serve only one. Calibrating the threshold on held-out data proved it, and adding the
cross-lingual rows back closed the gate. See `train/README.md`.

## The eval gate

`eval/` decides whether a fine-tuned cross-encoder is allowed to replace the served
one. 25 hand-labelled pairs, every one taken from a real pipeline run, over five
classes: `unrelated`, `incidental`, `meta`, `same_paraphrase`, `same_verbatim`.

```
python3 -m eval.run              # replay recorded scores, free and offline
python3 -m eval.run --scorer baseten
CLAIMTRACE_ALLOW_GPU=1 python3 -m eval.run --scorer local --path runs/xenc-5way
```

The class that earns the scheme its keep is `meta`. A verify run counts corroborating
posts, so a reply reading *"No public reports confirm any security incident at SSI"*
scoring high makes the tool report the opposite of the truth. A single relevance
score cannot express that, and the deployed model gets it wrong: its highest-scoring
negative is commentary about who reacted to an essay, at **0.813**, above every
genuine paraphrase in the set.

Gates split into **unlock** (the paraphrase failures the fine-tune exists to fix,
currently 0 of 3) and **regression** (the collisions already handled, currently 3 of
4 holding). Shipping needs all unlocks passing and no regression broken, so a model
that fixes recall by scoring everything high is rejected rather than celebrated.
