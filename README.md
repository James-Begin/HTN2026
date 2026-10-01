# Sequitor

**Follow a post back to the conversation it came from—and watch that conversation unfold.**

[Live app](https://sequitor-live-production.up.railway.app) · [Recorded demo (no API keys)](https://james-begin.github.io/HTN2026/) · [Watch the film](#watch-the-film)

Sequitor is a Hack the North 2026 project for exploring how a piece of information moves through X. Paste a post URL or enter a topic: it looks for a useful reference post, searches outward for related posts, and builds an interactive conversation space as the results arrive. Announcements, reactions, jokes, and paraphrases can all appear in the same investigation. The goal is to make the surrounding conversation legible, **not** to declare which post is true or prove that one author influenced another.

## Watch the film

https://github.com/user-attachments/assets/422bfae5-16eb-4b33-a314-2191ff0bc85e

The 46-second film is fully animated from the saved Dario investigation—not a screen recording. [Download the full-resolution MP4](docs/assets/sequitor-demo.mp4) or explore its [storyboard and reproducible Remotion source](video/README.md).

## Why this exists

By the time an interesting post reaches you, it may be a quote, a joke, or a reaction to something you have never seen. A keyword search returns a list, but it rarely shows how those posts relate. Sequitor starts with the post you have and gives you a way to inspect its possible source, the activity around a phrase, and the different ways people responded.

The central view plots retrieved posts around the reference post. The horizontal axis follows publication time; distance and direction in the other two dimensions come from seed-relative embedding similarity and a stable projection of semantic differences. Lines represent **observed** replies or quotes, when X provides them. The position of a node is an exploratory aid, not evidence of a causal relationship or a meaningful cluster by itself.

## How an investigation works

```mermaid
flowchart LR
    A[Post URL or topic] --> B[Resolve a reference post]
    B --> C[Plan search paths]
    C --> D[X counts and post search]
    D --> E[Embed and rank]
    E --> F[Conversation space + timeline]
    E --> G[Optional Baseten models]
    G --> F
```

1. **Find a reference.** For a URL, Sequitor resolves the post and inspects quote/reply parents. If the input looks like commentary, it searches for an earlier post that supplies the concrete premise. OpenAI can choose from *supplied candidate IDs*; the choice is verified before it becomes the anchor.
2. **Search beyond the seed text.** OpenAI produces a bounded plan with a phrase for activity counts and discovery queries for related posts. The backend combines X counts, phrase search, conversation search, and context expansion.
3. **Rank without flattening the story.** Embedding similarity, token overlap, direct reply/quote links, and retrieval scope are combined with a same-claim score when a reranker is available. A reaction can remain visible even when it is not the same claim.
4. **Build the view live.** The Python API emits Server-Sent Events (SSE). The React frontend progressively fills the activity chart, post feed, and Three.js conversation space. Reconnects resume the event log without repeating paid searches.

The saved Dario example replays locally without API calls. Live investigations require your own X and OpenAI credentials; Baseten routes are optional. See [backend architecture and evaluation](docs/BACKEND.md) for the exact signals and fallbacks.

## The model work

An off-the-shelf relevance reranker can rate a denial or a joke highly because it shares the topic. We curated **18,948** post pairs, including **6,343 cross-lingual pairs**, and fine-tuned OpenJev-4B with a five-way head: `same_verbatim`, `same_paraphrase`, `meta`, `incidental`, and `unrelated`. The first two classes form the same-claim score. Training ran on an H100 in a separate Baseten account; the model weights are not committed here. The inference adapter and optional Baseten Chain integration are in this repository.

| Model | 170-pair AUC | F1 at 0.5 | H100 throughput, batch 32 |
| --- | ---: | ---: | ---: |
| Fine-tuned BGE-large | **0.959** | 0.852 | ~4,700 pairs/s |
| Fine-tuned OpenJev-4B LoRA | 0.951 | **0.897** | ~264 pairs/s |

These are results on a small, curated evaluation set, not a general accuracy claim. BGE-large is much faster and slightly ahead on AUC; we used OpenJev for its five-way distinction and strong F1 at the chosen threshold. The full data, hard cases, measurement sources, and limitations are in [docs/BACKEND.md](docs/BACKEND.md). When a configured model route is unavailable, the live pipeline falls back to the remaining signals.

## Run locally

Requirements: **Python 3.12+** and **Node.js 22+**. The API itself uses the Python standard library; the frontend dependencies are pinned in `web/package-lock.json`.

```bash
git clone https://github.com/James-Begin/HTN2026.git
cd HTN2026
cp .env.example .env
cd web && npm ci && npm run build && cd ..
python3 sequitor_server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) and choose **Try Dario's post** for the keyless recorded demo. For live searches, put `X_BEARER` and `OPENAI_API_KEY` in `.env`. `BASETEN_API_KEY` and the model/Chain URLs enable optional model calls; see [.env.example](.env.example) for every setting. **Never commit `.env` or paste credentials into browser code.** Live X searches may incur API charges.

For frontend development, leave the Python server running and start `cd web && npm run dev` in another terminal; Vite proxies `/api`. For one-service deployment, see [Railway setup](docs/RAILWAY_DEPLOY.md). The [GitHub Pages version](https://james-begin.github.io/HTN2026/) is a recorded, offline demo.

## Explore the repository

| Path | What is there |
| --- | --- |
| `web/src/` | Landing experience, streaming UI, timeline, and Three.js conversation space |
| `sequitor_server.py` | Investigation API, SSE log, search, ranking, and spatial projection |
| `sequitor_anchor.py` | Reference-post selection and verification |
| `sequitor_openjev.py`, `baseten_*` | OpenJev and Baseten adapters |
| `claimtrace/` | X client, URL resolution, and embedding helpers |
| `demo/recordings/` | Saved investigations for the no-key demo |
| `mine/`, `train/`, `eval/`, `runs/suite/` | Data curation, training code, evaluation, and measured outputs |
| `docs/BACKEND.md` | Detailed pipeline, scoring weights, model comparison, and caveats |

To run the focused checks: `python3 -m unittest discover -s tests -t .` and `cd web && npm run build`.

This repository does not include model weights, service credentials, or the original training machine's environment. It also does not ship an automated claim-verification system: similarity and chronology help you investigate a conversation, but they cannot establish truth or provenance on their own.
