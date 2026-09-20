# Railway

One service, `sequitor-live`, serves the built UI and `/api` on the same origin.

- URL: https://sequitor-live-production.up.railway.app
- Dockerfile at the repo root; health check `/api/health`
- Volume `sequitor-data` mounted at `/data` (cache + SSE logs). The process will not start on Railway without it.
- Required: `X_BEARER`, `OPENAI_API_KEY`, `BASETEN_API_KEY`
- Optional: `SEQUITOR_OPENAI_MODEL`, `SEQUITOR_BASETEN_EMBED_URL`, `SEQUITOR_BASETEN_CHAIN_URL`, `SEQUITOR_JEV_RERANK_URL`
- `SEQUITOR_X_POST_CAP=0` disables Sequitor’s own post-read ledger (X billing still applies). `SEQUITOR_X_COUNTS_CAP` still limits count calls.

GitHub Pages is the offline recorded demo only.
