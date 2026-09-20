# Backend, ranking, and OpenJev

Numbers below come from checked-in files under `runs/suite/` and `eval/`. Same-claim probability is `P(same_verbatim) + P(same_paraphrase)` unless noted.

## Live search path

`POST /api/runs` with `{"seed":"...","mode":"live"}` starts a job. The browser reads `GET /api/runs/{id}/events` (SSE). Events are also written under the data dir so a reconnect does not rerun paid X calls.

```
paste
  → resolve seed (URL / syndication, then X lookup if needed)
  → walk quote/reply parents, or semantic-search a source post
  → OpenAI search plan (volume phrase + discovery queries)
  → X counts (histogram) → pick a day
  → X search (phrase, discovery, conversation_id, expansion)
  → embed + hybrid rank + 3D layout
  → OpenJev claim scores (if SEQUITOR_JEV_RERANK_URL)
  → Baseten Chain roles/edges (if SEQUITOR_BASETEN_CHAIN_URL)
  → run.completed
```

Recorded mode (`mode: "recorded"`) replays `demo/recordings/` and does not call X.

Caps: `SEQUITOR_X_POST_CAP` / `SEQUITOR_X_COUNTS_CAP` are Sequitor’s ledger on disk, not the X console. `0` disables the post cap.

## Hybrid rank

Each retrieved post gets:

| Signal | Weight with reranker | Weight without |
| --- | --- | --- |
| OpenJev `sameClaimScore`, else Chain `rerankerScore` | 0.45 | — |
| embedding cosine vs seed | 0.25 | 0.52 |
| token overlap | 0.18 | 0.25 |
| direct reply/quote of the seed | 0.08 | 0.18 |
| retrieval scope (conversation / discovery / phrase) | 0.04 | 0.05 |

Code: `Sequitor.rank_posts` in `sequitor_server.py`. OpenJev writes `sameClaimScore` and is preferred over BGE. Layout uses the same embedding vectors (`spaceY` / `spaceZ`).

## Why a 5-class head

Off-the-shelf rerankers treat “about the same topic” as a match. That promotes commentary and denials.

| Class | Meaning | Wanted score vs seed |
| --- | --- | --- |
| `same_verbatim` | same claim, same wording | high |
| `same_paraphrase` | same claim, different words | high |
| `meta` | talking about the claim / a reaction / a denial | low |
| `incidental` | shared tokens, different entity or event | low |
| `unrelated` | not the same subject | low |

## Data

`mine/` pulls outlet posts from Bluesky (keyless), joins on shared events, and labels real text. Combined set in `mine/README.md`: **18,948** pairs, **6,343** cross-lingual. Training split in `runs/suite/full_comparison_summary.json`: **16,841** train / **1,483** val, split by day so the same post is not on both sides.

Loss (BGE / Jev fine-tunes): 5-way CE plus BCE on the same-claim mass. English-only training separated English and failed cross-lingual; mixed-language rows are required.

## Model comparison

**25-pair hand gate** (`eval/pairs.jsonl`) and **170-pair gold** (`eval/gold_test_170.jsonl`). `jev` here is **untrained** OpenJev NLI. Fine-tuned OpenJev is `openjev_finetuned.json`.

| Model | 25 AUC | 25 F1@0.5 | 170 AUC | 170 F1@0.5 |
| --- | ---: | ---: | ---: | ---: |
| Served BGE (off-the-shelf replay) | 0.771 | 0.71 best-F1\* | — | — |
| OpenJev, no fine-tune | 0.877 | 0.625 | 0.859 | 0.253 |
| BGE-base FT (iter 1) | 0.955 | 0.909 | 0.935 | 0.870 |
| BGE-large FT (iter 3) | 0.994 | 0.909 | **0.959** | 0.852 |
| OpenJev-4B LoRA FT | 0.948 | **0.909** | 0.951 | **0.897** |

\*Off-the-shelf BGE has **no threshold** that separates the 25-pair set (margin −0.80). Best F1 is 0.71 at cutoff 0.26. Source: `eval/README.md`, `runs/baseline-off-the-shelf.json`.

H100 batch-32 throughput (`runs/suite/latency_comparison.json`): BGE-base **4.7k** pairs/s, BGE-large **4.7k**, OpenJev-4B LoRA **264** pairs/s. A live run scores ≤128 posts; wall time is still dominated by X.

### Hard pairs (same-claim score)

These are the cases that broke the stock reranker.

| Pair | Gold | Stock BGE | OpenJev (no FT) | BGE-large FT | OpenJev LoRA FT |
| --- | --- | ---: | ---: | ---: | ---: |
| `ssi-03` English paraphrase, no shared phrase | same | 0.29 | 0.11 | **0.98** | **0.99** |
| `ptf-03` Arabic coverage of the same announcement | same | 0.012 | 0.12 | **0.97** | **0.99** |
| `ptf-02` title + link vs full text | same | 0.26 | 0.09 | 0.97 | **0.98** |
| `ptf-05` commentary (“Elon agreed…”) | meta | **0.81** (false accept) | 0.008 | 0.009 | 0.031 |
| `ssi-05` acronym, different entity | incidental | ~0.03–0.47 | 0.003 | 0.010 | 0.009 |

Stock BGE: `runs/baseline-off-the-shelf.json`. BGE-large / OpenJev: `runs/suite/bge_iter3_large.json`, `jev_170.json`, `openjev_finetuned.json`.

What that means in the product: BGE-large is the better cheap ranker (highest 170 AUC). Fine-tuned OpenJev matches it on ranking and is what we serve for register (`sameClaimRegister`) plus the hybrid `sameClaimScore`. Untrained Jev is not used.

## Inference in production

1. `OpenJevReranker.score` (`sequitor_openjev.py`) POSTs `{reference, candidate}` batches to `SEQUITOR_JEV_RERANK_URL` (`/production/predict`). Writes `sameClaimScore`, `sameClaimRegister`, `rerankerModel`.
2. Optional Baseten Chain still labels response roles and observed X edges. Jev scores are kept if both run.
3. If Jev is down, `rank_posts` falls back to Chain `rerankerScore` (BGE) or embeddings + overlap only.

Adapter files: `baseten_openjev_4bit/` (LoRA on [AlexWortega/openjev](https://huggingface.co/AlexWortega/openjev)). Weights are not in git.

## Limits

- 170-pair **separation margin is still negative** for every model (one high-scoring negative or low-scoring positive). Ranking AUC is the number to use; min−max is not a shipping gate on noisy labels.
- On the 180-pair blind holdout, the earlier `xenc-best` checkpoint was AUC **0.916**, and **32 / 80** paraphrases still sat below 0.5 (`eval/README.md`). Paraphrase recall is better than stock BGE, not solved.
- The 25-pair gate overstates a “perfect” AUC. Use the 170-row table.

## Reproduce

```bash
python3 -m eval.run                              # replay recorded scores
python3 -m eval.run --compare runs/suite/bge_iter3_large.json runs/suite/openjev_finetuned.json
python3 -m train.run --describe                  # data mix, no GPU
```
