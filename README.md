# Sequitor

Paste an X post. Watch the conversation around it take shape.

Live demo: [sequitor-live-production.up.railway.app](https://sequitor-live-production.up.railway.app)

Recorded demo (no API keys): [james-begin.github.io/HTN2026](https://james-begin.github.io/HTN2026/)

Hack the North 2026. Built with OpenAI, X, and Baseten.

## What you get

1. Paste a post URL or a short query.
2. Sequitor finds a source post when you pasted commentary instead of the original.
3. It measures phrase activity on X and pulls related posts.
4. Posts land in a 3D conversation view, sized by reach, plus a readable sidebar.

Similarity and retrieval are not claims about truth, copying, or who influenced whom.

## Backend

A live search is one SSE job (`POST /api/runs` → `GET /api/runs/{id}/events`):

1. Resolve the pasted URL to a post (syndication, then X if needed).
2. If that post is commentary, walk quote/reply parents or search for a source post (`sequitor_anchor.py`).
3. OpenAI writes a bounded search plan (volume phrase + a few discovery queries).
4. X counts fill the histogram; X search fills the feed (phrase, conversation, expansion).
5. Posts are ranked and placed; OpenJev scores claim equivalence; an optional Baseten Chain adds roles/edges.

Recorded mode replays `demo/recordings/` and skips X. Details, rank weights, and model tables: [docs/BACKEND.md](docs/BACKEND.md).

Hybrid score when a reranker is present:

`0.45·same-claim + 0.25·embedding + 0.18·overlap + 0.08·reply/quote + 0.04·scope`

OpenJev’s `sameClaimScore` wins over BGE’s `rerankerScore`.

## OpenJev vs BGE

Stock BGE is a relevance reranker. It scores a *denial* or a *reaction* high because the wording is on-topic. We fine-tune a 5-class head (`same_verbatim`, `same_paraphrase`, `meta`, `incidental`, `unrelated`) on mined news pairs (`mine/`, 18,948 rows, 6,343 cross-lingual). Same-claim = verbatim + paraphrase.

| Model | 25-pair AUC | 25 F1@0.5 | 170-pair AUC | 170 F1@0.5 |
| --- | ---: | ---: | ---: | ---: |
| BGE off-the-shelf | 0.77 | —† | — | — |
| OpenJev, no fine-tune | 0.88 | 0.63 | 0.86 | 0.25 |
| BGE-large, fine-tuned | **0.99** | 0.91 | **0.96** | 0.85 |
| OpenJev-4B LoRA, fine-tuned | 0.95 | 0.91 | 0.95 | **0.90** |

†No cutoff separates the 25-pair set (margin −0.80). Best F1 is 0.71. Sources: `runs/suite/full_comparison_summary.json`, `openjev_finetuned.json`, `eval/README.md`.

Hard cases (same-claim score; want high on the first three, low on the last two):

| Pair | Stock BGE | OpenJev (no FT) | BGE-large FT | OpenJev FT |
| --- | ---: | ---: | ---: | ---: |
| English paraphrase, no shared phrase | 0.29 | 0.11 | 0.98 | 0.99 |
| Arabic coverage of the same announcement | 0.01 | 0.12 | 0.97 | 0.99 |
| Title+link vs full announcement | 0.26 | 0.09 | 0.97 | 0.98 |
| Commentary (“Elon agreed…”) | **0.81** | 0.01 | 0.01 | 0.03 |
| Acronym, different entity | low–mid | 0.00 | 0.01 | 0.01 |

BGE-large is the faster ranker (~4.7k pairs/s vs ~260 for Jev-4B on H100). Production uses fine-tuned OpenJev for the claim score and register; BGE remains the Chain fallback. Training: `train/`. Eval: `eval/`.

## Run it locally

```bash
cp .env.example .env   # add X_BEARER, OPENAI_API_KEY, BASETEN_API_KEY
cd web && npm ci && npm run build && cd ..
python3 sequitor_server.py
```

Open http://127.0.0.1:8765

For frontend work, run the Python server and `cd web && npm run dev` in two terminals. Vite proxies `/api`.

**Try Dario’s post** replays a saved capture (no X spend). Any other URL hits the live API.

Optional live model routes: `SEQUITOR_JEV_RERANK_URL`, `SEQUITOR_BASETEN_CHAIN_URL` (see `.env.example`).

Deploy notes: [docs/RAILWAY_DEPLOY.md](docs/RAILWAY_DEPLOY.md)

## Stack

| Piece | Role |
| --- | --- |
| `web/` | React / Three.js UI |
| `sequitor_server.py` | SSE investigation API |
| OpenAI | Search plan from the seed text |
| X API | Counts and post retrieval |
| OpenJev (Baseten) | Fine-tuned 5-class same-claim score |
| BGE / Baseten Chain | Fallback rerank, roles, observed edges |

## Repo layout

```
web/                 browser app
sequitor_server.py   live + recorded runs
sequitor_anchor.py   source-post resolution
sequitor_openjev.py  OpenJev Baseten client
claimtrace/          X client, resolver, embeddings
demo/recordings/     saved Dario / anchor fixtures
docs/BACKEND.md      pipeline, rank weights, Jev vs BGE
train/ eval/ mine/   data, fine-tune, gates
runs/suite/          measured comparison JSON
cli.py               older claimtrace CLI
```

## Tests

```bash
python3 -m unittest discover -s tests -t .
cd web && npx tsc -b
```
