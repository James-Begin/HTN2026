# Handoff: what's been built, and why

This is the narrative version. `README.md` and the five subdirectory READMEs are
reference documentation for using and understanding the system as it stands; this
doc is the story of how it got there, so the next phase (the frontend) can be built
on an accurate picture rather than a re-derived one.

**One-line summary:** claimtrace takes a claim or a tweet URL and either traces its
lineage back through the archive or gives an honest read on whether anyone actually
corroborates it. The backend, the mined training data, the fine-tuned model, and the
evaluation discipline behind it are done. The frontend is next, and this doc is
written for whoever builds that.

---

## Phase 0 — the pipeline

`resolve -> extract -> shape -> route -> (verify | lineage) -> judge -> compose`,
backed by the X API and Baseten. Two design choices from this phase still shape
everything downstream:

- **Everything observable goes out through an event stream** (`claimtrace/events.py`),
  not a return value. The terminal renderer and any future web frontend consume the
  identical stream; `--json` already emits NDJSON, which is SSE-ready with no
  format change.
- **A four-state resolver** (LIVE / DELETED / PROTECTED / GONE, keyless, via
  Snowflake ID decoding) treats a deleted tweet as a positive finding rather than a
  failure, because a deleted-but-decoded post is exactly the case the tool exists
  to handle.

`route()` decides VERIFY vs LINEAGE from pre-spike volume on a 30-day curve, not
from whether the spike itself is recent — a routing rule that is genuinely
time-relative (the same claim measured VERIFY at two hours old and LINEAGE a day
later, since volume decays out of the window).

## Phase 1 — the eval gate, and the number that started everything

The served cross-encoder (an off-the-shelf single-logit reranker) was measured, not
assumed to be fine. On the first 25 hand-labelled pairs its **separation margin was
-0.80**: the worst true positive scored 0.012 and the best true negative scored
0.813, so *no threshold classified the set correctly*. That number is what justified
everything that follows — mining data, building a labeller, training a checkpoint.

The eval set grew twice, each time because the smaller set was overstating things:

| Set | n | Purpose |
|---|---|---|
| `eval/pairs.jsonl` | 25 | the release gate: known failures, hand-picked, hand-labelled |
| `eval/holdout.jsonl` | 180 | blind-labelled (scores withheld during labelling), half sampled from the actual decision boundary |
| `eval/fresh.jsonl` | 68 | a **temporal** holdout: days collected strictly after the training corpus ends |

The 180-pair set caught the 25-pair gate reporting AUC 1.000 when the real number
(measured the same way, on more pairs) was 0.92. The 68-pair fresh set caught
something more useful: AUC drops from 0.98 in-window to 0.89 out-of-window for
**every** model tested, baseline and fine-tuned alike, by almost the same amount —
so the drop is the fresh set being genuinely harder, not the fine-tune overfitting.

Gates split into **unlock** (paraphrase failures the fine-tune exists to fix) and
**regression** (collisions the served model already handled and must keep
handling). A model that fixes recall by scoring everything high fails the second
kind, which is why both are tracked and neither alone decides "shippable."

## Phase 2 — mining real training data, not generating it

The one rule that held for the whole mining effort: **the model may find and label
pairs, but it never writes the text.** Generated paraphrases would measure how well
a model learned its own generator's habits; mined pairs introduce label noise
instead, which is smaller and, critically, measurable.

Bluesky was the source, for one reason: keyless and free, where X bills per row
returned. The join key took real iteration to get right:

- **Shared outlinks were the first plan and the data killed it.** Outlets link their
  own article and shorten it differently, so two outlets covering the same event
  share no URL. Of an early 4,473-post sample, exactly one pair exceeded Jaccard
  0.85 on that basis.
- **Shared rare tokens in a narrow time window worked.** Independent newsrooms reuse
  proper nouns and numbers and little else, so a candidate join on 2-3 shared rare
  tokens inside a 1-day window found real paraphrase pairs at low lexical overlap —
  exactly the shape the served model failed on.
- **Non-Latin scripts needed a translation bridge**, because Arabic and Japanese
  posts carried Latin tokens in 0-7% of samples and so joined with nothing. The
  bridge translates *only to compute the join*; the stored pair keeps the original
  text, and language detection reads the original, never the translation.
- **Yield scales with outlet-pair count and calendar overlap, not post count.**
  Tripling a corpus by paging further back raised candidates only 41%, because the
  extra pages fell outside where outlets' coverage windows overlapped. Paging every
  outlet to a common floor date instead of a common page count fixed it.

The labelling itself needed two iterations. A single 5-way prompt was 77.8% exact
against hand labels overall but **only 14% accurate on `meta`** (commentary, denials,
questions about a claim's source) — and it failed in a specific, structural way: a
curated newsroom account essentially never replies to another newsroom, so a
dedicated meta-detector asked on outlet-vs-outlet pairs over-fired on obituaries and
co-reports. Gating the meta question on provenance (only ask it when B is a reply,
not an outlet) and keeping the 5-way prompt for everything else took `meta` accuracy
from 14% to 89% and overall exact agreement from 77.8% to 84.4%.

Beyond mined event pairs, three **structural** generators were built to fix specific
measured failures rather than add generic volume: truncation pairs (a real-tweet
failure mode: a retweet cut mid-sentence), headline-asymmetry pairs (a short
title-plus-link against the same post's own longer lede), and entity-collision pairs
(same named entity, weeks apart, so a different claim — the acronym-collision shape
that broke a regression gate once already).

## Phase 3 — training

The objective is not plain cross-entropy. Measured label agreement against hand
labels was 94% on the same-vs-not decision and only 74% on the exact 5-way subtype,
so the loss adds a binary term on same-claim probability specifically, weighted
higher than the 5-way term, because that is the more trustworthy signal and the
quantity every downstream gate is actually defined on.

**The split is by calendar day, not by row.** 21% of mined posts appear in more than
one training pair; a random row split would put the same post's text on both sides
of the train/validation boundary and inflate every number. Whole days are held out
instead, and any pair whose two posts straddle the boundary is dropped.

**Two experiments were tried and rejected, both by measurement:**

- A smaller 278M base model (roughly half the serving cost) lost cleanly on the
  gate — 1 of 3 unlock gates against 3 of 3 for the 568M model — so the throughput
  win wasn't worth the accuracy loss.
- Loosening the mining join threshold to get more paraphrase volume did increase
  recall, but broke a regression gate that was previously solid (an acronym
  collision, `ssi-05`), because the looser join let in enough genuinely-different
  pairs to teach the model to accept on thinner evidence than it should.

**Training moved to CPU** when the shared GPU box was externally contended, and two
non-obvious things mattered enough to be worth stating: thread count optimal is
*model-size- and batch-shape-dependent* (16 threads beat 96 on a small model with
long batches; 64 beat 16 on a large model with short batches; the reversal is real
and about 2.7x), and **length-grouped batching** (sorting within a shuffled
megabatch rather than fully at random) cut mean batch length roughly in half and
step time by a third, because random batching pads every sequence in a batch to
that batch's own maximum.

## Phase 4 — the fresh-holdout validation, and the reframe it forced

After training, the 68-pair fresh holdout (Phase 1) produced the most important
correction of the whole project: the aggregate metric drop on unseen days looked
alarming (AUC -0.09) until it was broken down by the tool's actual three-state
gate (accept / uncertain / reject) rather than one cutoff. Of 29 genuine fresh
paraphrases, only 2 were silently lost to `reject`; 10 landed in `uncertain`, which
is shown to a human with a flag rather than hidden. Of what the tool actually
accepted, precision was 85%.

That reframe changed the priority ordering. Chasing more aggregate AUC had already
shown diminishing-to-negative returns (both rejected experiments above), and the
three-state design was already absorbing most of the apparent gap. The higher-value
move was **re-deriving the accept/reject thresholds specifically to minimize the
cases the gate actually silently drops**, not training harder — this is documented
in `claimtrace/config.py`'s `XENC_ACCEPT`/`XENC_REJECT` comments, calibrated on 145
combined blind-labelled English pairs and verified by hand: of the false accepts at
the old threshold, 3 of 4 were genuine model errors and were removed by raising the
threshold; of the "unrescuable" misses, 3 of 4 turned out to be defensible labelling
judgment calls on inspection, not clean model failures.

One real bug was caught in the course of that recalibration: `eval/run.py` and
`eval/metrics.py` computed the report's headline numbers correctly at a custom
`--threshold`, but three display paths (`per_class`'s "wrong side" count, the
per-case pass/fail marks, and the printed metric labels) stayed silently pinned to
the module default of 0.5. Fixed, with a CLI-level regression test asserting the
printed label text matches the threshold that was actually passed.

## Phase 5 — deployment

The TensorRT engine builder path (Baseten's fast native serving option) was tried
and blocked on two independent things: it only accepts checkpoints staged on HF, S3,
GCS, Azure, or a URL, and there was nowhere appropriate to stage a personal research
checkpoint (no HF token, and the only cloud credentials present belonged to an
unrelated production system); and `base_model: encoder_bert` is documented as
BERT-only, while the checkpoint is XLM-RoBERTa, so engine support was unverified
anyway. A custom Truss was built instead, deliberately matching the request/response
shape of Baseten's own `/rerank` route so the existing client code needed only a URL
change, plus a `distribution` field carrying the full 5-class output (the register a
single relevance score cannot express).

Verified end to end: fp16-converted weights reproduce local fp32 scores to within
0.0032 across all 205 hand-labelled pairs, with **zero pairs crossing the accept
threshold differently**. Measured throughput is 434 pairs/sec at concurrency 16
against 2,851 for the served single-logit model on the TensorRT engine — a 6.6x cost
judged affordable because one pipeline run scores roughly 50 candidates (0.12s)
inside a 14-66s wall time dominated entirely by the X API's rate limit.

**As of this writing, the fine-tune is not deployed.** Baseten was explicitly
deactivated partway through (all three known deployments confirmed INACTIVE, zero
active replicas) and the credentials used to manage it are no longer present in this
environment. Deploying `runs/sweep-en/en-m3` (or whatever supersedes it) and pointing
`claimtrace/config.py` at the new endpoint is the first thing that needs doing before
any live demo.

---

## Current state, plainly

| | Status |
|---|---|
| Pipeline (resolve/extract/shape/route/verify/lineage/judge/compose) | built, tested, works against live X + Baseten |
| Event stream contract | built; `--json` emits NDJSON, ready for SSE |
| Terminal renderer | built, reference implementation of consuming the event stream |
| Mined + labelled English training data | ~19k rows, built, committed |
| Fine-tuned checkpoint | `runs/sweep-en/en-m3` passes its gate; **not gitignored, not committed** (37GB of checkpoints across all experiments; see `.gitignore`) |
| Deployment | custom Truss built and previously verified live; **currently deactivated** |
| Groundedness verifier for the composer's output | designed, not built |
| Cross-platform retrieval (Bluesky/Reddit/Wayback) *in the live pipeline* | not built — the pipeline still only searches X, even though Bluesky is now used heavily for training data |
| Cross-lingual / Arabic support | explicitly out of scope by decision; the one Arabic outlet found on Bluesky has been dormant since January |

## What the frontend needs to know

- **The event stream is the integration point, not the pipeline internals.**
  `claimtrace/events.py` defines every event kind (CLAIM, RESOLVED, STAGE, EXTRACT,
  SHAPE, ROUTE, PROBE, EARLIEST, SIGNAL, PREMISE, CASCADE, SCORE, HEADLINE, TOKEN,
  NOTE, DONE, ERROR). Build against that contract and the terminal renderer
  (`claimtrace/render.py`) is a working second consumer to check behavior against,
  not the thing to extend.
- **`cli.py` is the reference orchestrator**, not a special case — it calls
  `claimtrace/pipeline.py:run()` and wires the event stream to a sink. A web backend
  wrapping the same `run()` call with a different sink (writing SSE instead of ANSI)
  is the natural shape.
- **The SCORE event now carries `verdict` (accept/uncertain/reject) and `register`**
  (the 5-class argmax), added when the fine-tune was wired in. `render.py` shows
  `meta` in red specifically, because a denial or commentary scoring as corroboration
  is the tool's single most expensive failure mode. Any new renderer should preserve
  that distinction, not just show a bare score.
- **The model currently live in `claimtrace/config.py` is stale.** `XENC_MODEL_ID`
  points at a deployment that is deactivated. Don't build against it without
  re-deploying and re-checking `XENC_ACCEPT`/`XENC_REJECT` first — both are
  checkpoint-specific and have already silently gone wrong once after a retrain.
- **`demo/cases.jsonl`** has 8 verified demo cases with honest cost/risk notes,
  including which ones will drift by the time anyone runs them (routing is
  time-relative) and which three are free and cannot fail (keyless resolves).

## Explicitly out of scope, not forgotten

- **Arabic and cross-lingual generally.** Scoped out on request. The infrastructure
  (translation bridge, script detection across 9 languages) exists and was validated
  on Japanese; it would need a live source, most likely paid X search rather than
  Bluesky.
- **Groundedness verification.** The composer has hallucinated at least once (a
  corporate commitment invented outside the evidence). Flagged early, never started;
  needs its own small hand-labelled set before any model work, same discipline as
  everything above.
- **In-pipeline cross-platform retrieval.** Bluesky, the Reddit archive, and the
  Wayback index are all free and would extend `claimtrace/xapi.py`'s role to sources
  beyond X. Largest remaining capability gap, lowest priority unless a demo needs it.

## Where to go for depth

Each subdirectory README goes deeper on its own phase, with the actual measured
numbers behind every claim above: `README.md` (the pipeline and its measured facts),
`mine/README.md` (mining and the labeller), `train/README.md` (the fine-tune and its
rejected experiments), `eval/README.md` (the gate and the holdouts), `deploy/README.md`
(serving mechanics and the threshold calibration), `demo/README.md` (the demo cases
and what's fair to claim about the model).
