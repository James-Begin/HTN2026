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

## Run it locally

```bash
cp .env.example .env   # add X_BEARER, OPENAI_API_KEY, BASETEN_API_KEY
cd web && npm ci && npm run build && cd ..
python3 sequitor_server.py
```

Open http://127.0.0.1:8765

For frontend work, run the Python server and `cd web && npm run dev` in two terminals. Vite proxies `/api`.

**Try Dario’s post** replays a saved capture (no X spend). Any other URL hits the live API.

`SEQUITOR_X_POST_CAP` is a local/Railway ledger cap, separate from your X account balance. `0` turns that cap off. See `.env.example`.

Deploy notes: [docs/RAILWAY_DEPLOY.md](docs/RAILWAY_DEPLOY.md)

## Stack

| Piece | Role |
| --- | --- |
| `web/` | React / Three.js UI |
| `sequitor_server.py` | SSE investigation API |
| OpenAI | Search plan from the seed text |
| X API | Counts and post retrieval |
| Baseten | Optional embeddings, curation, rerank |

## Repo layout

```
web/                 browser app
sequitor_server.py   live + recorded runs
sequitor_anchor.py   source-post resolution
claimtrace/          X client, resolver, rerank helpers
demo/recordings/     saved Dario / anchor fixtures
tests/               unit tests
train/ eval/ mine/   claim-equivalence model work
cli.py               older claimtrace CLI
```

## Tests

```bash
python3 -m unittest discover -s tests -t .
cd web && npx tsc -b
```
