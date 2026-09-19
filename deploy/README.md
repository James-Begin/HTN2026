# Serving the fine-tune on Baseten

The fine-tuned 5-class cross-encoder, live and wired into the pipeline.

```
truss push deploy/xenc                    # 1.1GB weights bundled, ~12 min to ACTIVE
python3 -m eval.run --scorer deployed     # the gate, through the endpoint
python3 -m eval.run --scorer deployed --holdout
python3 deploy/bench.py                   # latency and throughput
```

Model `q9p28o63`, route `environments/production/predict`, one L4.

---

## Why a custom Truss and not the TensorRT engine builder

Two blockers, both real rather than stylistic.

**Nowhere appropriate to stage the checkpoint.** The engine builder accepts a
checkpoint only from Hugging Face, S3, GCS, Azure or a presigned URL. There is no
Hugging Face token on this machine, and the only AWS credentials are an assumed
production role belonging to someone else's infrastructure, which is not a place to put
a personal research checkpoint.

**Architecture support is unverified.** `base_model: encoder_bert` is documented as
"for BERT-based models". This checkpoint is `XLMRobertaForSequenceClassification`. The
earlier working deployment was `bge-reranker-base`, which is BERT-based, has a single
logit, and came from a public HF repo. All three differ now.

One thing the docs did settle: the route for a 5-class head is **`/predict`**, not
`/rerank`. `webserver_default_route` lists `/rerank` "for reranking models" and
`/predict` "for sequence classification models". That resolves the question flagged
early on about whether a 5-logit head could serve on `/rerank` at all: it should not,
and it does not need to.

## The response shape is deliberately `/rerank`-compatible

`{query, texts}` in, `[{index, score}]` out. So `claimtrace/baseten.py` needed no
change beyond the URL. What is added is `distribution`, the full 5 classes, because
a single relevance logit cannot express register and register is what stops a denial
being counted as corroboration.

---

## It serves faithfully

Weights were converted to fp16 for serving, halving them from 2.1GB to 1.1GB. Across
all 205 hand-labelled pairs, deployed against local fp32:

| | max score difference | mean |
|---|---|---|
| 25-pair gate | 0.0025 | 0.0002 |
| 180-pair holdout | 0.0032 | 0.0003 |

**Zero pairs cross the accept threshold differently.** The gate reproduces exactly:
4 of 4 unlock, 7 of 7 regression, SHIPPABLE, ROC AUC 1.0000. The holdout reproduces
too, at AUC 0.9161 against 0.9156 locally.

One bug worth recording: the checkpoint was saved by transformers 5.x, which writes
`dtype` to `config.json`, while 4.x reads `torch_dtype`. Pinning the older library
would have silently loaded fp32 and doubled memory. The config now carries both keys.

## Throughput: the fine-tune costs 6.6x, and it does not matter

Measured on real headline text, median 94 characters:

| batch | p50 latency | pairs/sec |
|---|---|---|
| 1 | 125 ms | 8 |
| 8 | 123 ms | 65 |
| 32 | 160 ms | 200 |
| 64 | 237 ms | 270 |

| client concurrency | pairs/sec |
|---|---|
| 1 | 181 |
| 4 | 340 |
| 8 | 373 |
| 16 | 434 |

The off-the-shelf 1-logit reranker on Baseten's TensorRT engine did **2,851 pairs/sec**
on the same GPU class. So this is about 6.6x slower.

That is affordable, and the reason is worth stating precisely rather than waving at.
A pipeline run scores roughly 50 candidates, which is 0.12 seconds at 434 pairs/sec,
against a wall time of 14 to 66 seconds dominated by the X API and its one-request-per
-second throttle. The exhaustive-pairwise-scoring argument survives easily. Where the
6.6x would bite is bulk offline re-scoring, and even there the 9,874 mined candidates
take 23 seconds.

Batch 1 and batch 8 cost the same 125 ms, so that latency is round-trip and server
overhead rather than compute. Callers should batch; `XENC_BATCH` is 32.

---

## Two thresholds, because one cannot express what this tool needs

Measured on the 180-pair holdout, through the live endpoint:

| threshold | precision | recall | false accepts | missed |
|---|---|---|---|---|
| 0.30 | 0.808 | 0.962 | 24 | 4 |
| 0.40 | 0.863 | 0.838 | 14 | 17 |
| 0.50 | 0.890 | 0.695 | 9 | 32 |
| 0.70 | 1.000 | 0.333 | 0 | 70 |

A false accept is the expensive error here. Verify mode COUNTS corroborating posts, so
scoring commentary or a denial as a restatement makes the output assert the opposite of
the truth. A missed paraphrase only loses a citation. So the gate accepts at **0.70**,
rejects below **0.32**, and abstains in between rather than guessing.

### The abstain band earns its place on the exact case that broke the gate

Scored live against the real claim:

| verdict | score | register | gold | off-the-shelf |
|---|---|---|---|---|
| accept | 0.9914 | `same_verbatim` | `same_verbatim` | 1.0000 |
| accept | 0.8660 | `same_paraphrase` | `same_paraphrase` | **0.2880** |
| uncertain | 0.4252 | `incidental` | `incidental` | n/a |
| reject | 0.1989 | `meta` | `meta` | 0.4009 |
| reject | 0.0345 | `meta` | `meta` | n/a |

Row three is `ssi-05`, Supplemental Security Income from 2017 against Safe
Superintelligence. It is the pair that failed a regression gate at threshold 0.32 and
passed only marginally at 0.5. Under two thresholds it lands in `uncertain`, which is
the honest answer: the model does not know, and the register still correctly says
`incidental`.

Row four is the reply asking for a source, and row five denies the claim outright. Both
are rejected AND tagged `meta`, so neither can be counted as corroboration. The
off-the-shelf model scored the first of them 0.4009 with no register at all.

## What is wired where

| File | Change |
|---|---|
| `claimtrace/config.py` | `XENC_MODEL_ID`, route, accept/reject thresholds, measured throughput |
| `claimtrace/baseten.py` | full-route URLs, `want_dist`, `last_distributions` |
| `claimtrace/pipeline.py` | `judge()` returns accept/uncertain/reject plus register |
| `claimtrace/events.py` | `score` carries `verdict` and `register` |
| `claimtrace/render.py` | verdict marks, and `meta` flagged in red |
| `eval/scorers.py` | `DeployedScorer` for `--scorer deployed` |

`XENC_BASELINE_ID` still points at `qrpmm003`, the off-the-shelf deployment, because it
is the number the fine-tune is measured against.
