# Claim-equivalence eval

The gate between a local checkpoint and the Baseten deployment. Nothing here
trains, and nothing touches a GPU unless you ask for the local scorer explicitly.

```
python3 -m eval.run                      # replay recorded scores. free, offline, 0.2s
python3 -m eval.run --describe           # the set, by class
python3 -m eval.run --scorer baseten     # measure the deployed cross-encoder
python3 -m eval.run --save runs/base.json
python3 -m eval.run --compare runs/base.json runs/candidate.json
python3 -m unittest tests.test_eval      # 50 tests, no network, no cost
```

The local scorer refuses to start unless `CLAIMTRACE_ALLOW_GPU=1` is set. The cards
on this machine are shared, so an accidental `--scorer local` must not claim one.

---

## Why five classes

`unrelated`, `incidental`, `meta`, `same_paraphrase`, `same_verbatim`, in that
order. Same-claim probability is the sum of the last two, and register falls out of
the argmax. One softmax head, because that serves cleanly on Baseten's embeddings
engine and a multi-head model very likely would not.

The distinction that earns the scheme its keep is **meta versus same_paraphrase**.
A verify run counts corroborating posts. If a reply reading *"No public reports
confirm any security incident at SSI"* counts as corroboration, the tool reports the
opposite of the truth. A single relevance score cannot express that difference; it
scores the disputing reply high because it is obviously on-topic.

`incidental` is separate from `unrelated` for the same reason. The Korean honorific
`-ssi`, the Oklahoma fight song *Boomer Sooner*, and Supplemental Security Income
are not noise. They are the specific collisions that a keyword bisect actually
returned, and a model that lumps them with random spam has not learned the hard
part.

---

## Baseline: the deployed cross-encoder

14 of the 25 pairs have a recorded score from real pipeline runs. Replaying them:

| Class | n | want | mean | min | max | wrong side of 0.5 |
|---|---|---|---|---|---|---|
| `unrelated` | 3 | low | 0.0003 | 0.0000 | 0.0010 | 0 |
| `incidental` | 2 | low | 0.2198 | 0.0343 | 0.4053 | 0 |
| `meta` | 3 | low | 0.4094 | 0.0147 | 0.8127 | 1 of 3 |
| `same_paraphrase` | 2 | high | 0.1500 | 0.0120 | 0.2880 | 2 of 2 |
| `same_verbatim` | 4 | high | 0.8150 | 0.2611 | 1.0000 | 1 of 4 |

| Metric | Value |
|---|---|
| separation margin | -0.8007 |
| ROC AUC | 0.7708 |
| average precision | 0.7903 |
| Brier | 0.2154 |
| expected calibration error | 0.2863 |
| precision at 0.5 | 0.7500 |
| recall at 0.5 | 0.5000 |
| best F1 at any threshold | 0.7143 |
| coverage at 100% precision | 21.4% |

### The headline number is the separation margin

`min(positive) - max(negative)` is **-0.8007**. That is not "the threshold needs
tuning". It means **no threshold exists** that classifies this set correctly. The
best F1 reachable at *any* cutoff is 0.71, and it lands at 0.2611, which is the
score of a post consisting of the essay's exact title plus a link to the essay.

### A second failure the recall framing hides

Writing this up surfaced something the earlier notes missed. The highest-scoring
negative in the whole set is `ptf-05` at **0.8127**:

> Elon, perhaps the last person I would've thought would agreed that we must pace
> the frontier

That is commentary about who reacted to the essay. It outscores every genuine
paraphrase, including the faithful English restatement at 0.288 and the Arabic
coverage of the same announcement at 0.012. So the served model has a **false
accept** problem, not only a recall problem, and a fine-tune that only pushes
paraphrases up would move the failure rather than remove it. This is why the
regression gates exist and why `ptf-05` is one of them.

The three cross-lingual and short-text failures point the same way:

| id | Pair | Should be | Scores |
|---|---|---|---|
| `ptf-03` | Arabic coverage of the same essay announcement | `same_paraphrase` | 0.0120 |
| `ptf-02` | the exact title plus a link to the essay | `same_verbatim` | 0.2611 |
| `ssi-03` | plain English restatement, no shared phrase | `same_paraphrase` | 0.2880 |

0.012 on a correct cross-lingual restatement is the strongest single argument for a
multilingual base model rather than an English-only one.

---

## The 180-pair holdout, and what it revealed

`eval/holdout.jsonl` is 180 pairs labelled by hand, **blind to the model score and to
the pipeline labeller's answer**. Both were withheld during labelling and joined back
only afterwards, so the labels cannot have been anchored by them. Pairs were drawn from
the validation days, which training already excludes, with half sampled from the
0.30-0.70 score band because that is where the accept decision happens and where there
was almost no labelled evidence: 61% of scores sit below 0.1 and 23% above 0.9.

```
python3 -m eval.run --scorer local --path runs/xenc-best --holdout
```

### The 25-pair gate was overstating performance

| Metric | 25-pair gate | 180-pair holdout |
|---|---|---|
| ROC AUC | 1.0000 | 0.9156 |
| average precision | 1.0000 | 0.9334 |
| precision at 0.5 | 1.0000 | 0.8902 |
| recall at 0.5 | 0.8182 | 0.6952 |
| F1 at 0.5 | 0.9000 | 0.7807 |
| separation margin | +0.0056 | -0.6610 |
| coverage at 100% precision | 44% | 19% |
| best-F1 threshold | 0.4305 | 0.3194 |

The gate said SHIPPABLE with a perfect AUC. On seven times as many pairs, weighted
toward the decision boundary, AUC is 0.916 and **32 of 80 `same_paraphrase` pairs still
score below 0.5**. The paraphrase problem is much improved from 0.288 on one pair, but
it is not solved: at the default threshold the model misses about 40% of genuine
paraphrases.

The holdout also puts the threshold question to rest in the other direction. Best F1
lands at 0.319, well below both the gate's passing band of 0.425 to 0.582 and the
default 0.5. Three independent estimates now point below 0.5: validation at 0.399,
mixed-language validation at 0.253, and this holdout at 0.319.

### Where the pipeline labeller actually fails

Agreement on this harder sample is 77.8% exact and 85.6% binary, against 74.3% and
94.3% measured on the original 21. Binary agreement is LOWER here because the sample is
deliberately harder, which is the honest number for boundary cases.

The failure is concentrated in one place:

| Gold class | What the labeller said instead |
|---|---|
| `meta` (21) | `same_paraphrase` 8, `incidental` 8, `unrelated` 2 |
| `same_paraphrase` (80) | `incidental` 14, `same_verbatim` 1 |
| `incidental` (26) | `same_paraphrase` 4 |
| `unrelated` (28) | `incidental` 3 |

**The labeller gets `meta` right 11 times out of 21, and calls 8 of them
`same_paraphrase`.** That is the dangerous direction: a verify run counts corroborating
posts, so commentary and denials scored as restatements invert the conclusion. The
1,436 `meta` rows in the training set are correspondingly contaminated, which is a
concrete reason the class is still the weakest.

### One caveat about this holdout, stated rather than buried

All 25 `same_verbatim` pairs in it come from the truncation and headline-asymmetry
generators, the same structural shapes used in training. The model scores them 25 of 25
correctly with a mean of 0.991 and a minimum of 0.984. That is shape recognition, not
evidence of generalisation, and the class should be read as untested here rather than
as solved. Real verbatim pairs barely exist in a news corpus because outlets rewrite.

---

## Gates

Two kinds, reported separately, never as one pass/fail. "8 of 9" tells you which
direction to go; "FAIL" does not.

**Unlock** gates are the failures that motivate the fine-tune at all: `ssi-03`,
`ptf-03`, `ptf-02`, `dril-01`, `boom-02` must all reach 0.5. Currently 0 of 3
measurable.

**Regression** gates are the collisions the off-the-shelf model already handles and
must keep handling: the Korean honorific, Supplemental Security Income, the
Oklahoma fight song, entity-only overlap, one-word spam, the disputing reply, the
false accept at 0.813, and the live follow-up six hours after the deleted covfefe
original. Currently 3 of 4 measurable hold, with `ptf-05` already broken.

**Aggregate** gates are advisory until the set is bigger. Expected calibration error
over 25 pairs is noise; it is wired in now so the hyperparameter sweep has a target
from day one, since calibration is the metric that actually decides whether
abstention is real or theatre.

A checkpoint ships when every unlock gate passes **and** no regression gate breaks.
Test coverage enforces the obvious cheat: `test_not_shippable_when_a_regression_breaks`
scores every pair 0.99 and asserts the harness rejects it.

---

## What the eval deliberately does not do

- **It never exits non-zero.** This is a measurement, not a test. A failing gate
  today is the expected state.
- **Unmeasured pairs are skipped, not defaulted to zero.** Defaulting would flatter
  a new model on negatives and punish it on positives, in the same run.
- **Debatable labels do not gate.** Two pairs are marked `debatable`: `ptf-08` (the
  slogan usage predating the essay by a month) and `twtr-02` ("just setting up my
  bluesky"). They are scored and shown, never gated, because failing them may mean
  our label is wrong. `test_gated_ids_are_not_debatable` enforces this.

---

## Order of work from here

1. **Fill the 11 missing baselines.** `python3 -m eval.run --scorer baseten --save runs/base.json`.
   Network only, no GPU, a few cents, needs the deployment awake. Do this before
   training so the comparison is complete rather than partial.
2. **Grow the set to 200-300 pairs.** 25 is enough to gate on and far too few for
   calibration. Every hand-labelled pair should come from a real pipeline run, the
   way these did. Synthetic pairs go in a separate file so they never contaminate
   the gate.
3. **Train the 5-class head locally.** `id2label` must match `LABELS` exactly; the
   harness raises rather than silently permuting, and Baseten's engine build fails
   outright without it.
4. **Sweep, selecting on separation margin and calibration**, not on accuracy.
   Accuracy at 0.5 is satisfiable by a model that is useless at any other threshold.
5. **Push to Baseten only when `shippable` is true.**

## Layout

```
eval/pairs.jsonl     25 hand-labelled gate pairs, every one from a real run
eval/holdout.jsonl   180 hand-labelled pairs, blind-labelled, reported not gated
eval/sample.py       draws review candidates with scores and machine labels stripped
eval/join_review.py  joins hand labels back on and measures labeller agreement
eval/dataset.py      schema, loader, validation, reference grouping
eval/metrics.py      ranking, thresholded, calibration, coverage, per-class
eval/gates.py        unlock / regression / aggregate release criteria
eval/scorers.py      replay (free) | baseten (deployed) | local (checkpoint)
eval/run.py          runner, report, --save, --compare
tests/test_eval.py   50 tests, no network, no GPU
```
