# Sequitor Baseten Chain

`sequitor_chain.py` is a four-Chainlet analysis pipeline for posts already retrieved by the Sequitor server. `SequitorAnalysis` fans out Baseten hosted-model curation, extraction of X-observed reply/quote edges, and a compact `BAAI/bge-reranker-base` cross-encoder on an L4. It then streams each result as SSE. It never fetches from X and does not consume X credits.

The server uses [`sequitor_baseten_chain.py`](../sequitor_baseten_chain.py) as its client adapter. Set `SEQUITOR_BASETEN_CHAIN_URL` to the deployed Chain's `/environments/production/run_remote` endpoint. The adapter is opt-in: if there is no endpoint, keep the server's hosted-model fallback.

Deploy after this Baseten account is allowed to create deployments:

```sh
uv tool run truss@latest login --remote sequitor-hackathon --api-key "$BASETEN_API_KEY"
uv tool run truss@latest chains push chains/sequitor_chain.py --name Sequitor-BGE-Baseline --remote sequitor-hackathon --promote --wait
```

Avoid putting the API key in a tracked file. The Chain obtains Baseten's internal key from `DeploymentContext.get_baseten_api_key()`. The request body contains at most 32 already retrieved posts and a seed text. The Chain returns `analysis.started`, `observed.ready`, `rerank.ready`, `curation.ready`, and `analysis.completed` events; each `data:` payload is JSON. `rerank.ready` is a relevance signal for hybrid retrieval only; it does not establish a source, a causal relationship, or whether a post is true.

The local dry run is:

```sh
uv tool run truss@latest chains push chains/sequitor_chain.py --dryrun
```

See [Baseten's Chain deployment guide](https://docs.baseten.co/development/chain/deploy), [invocation guide](https://docs.baseten.co/development/chain/invocation), and [streaming guide](https://docs.baseten.co/development/chain/streaming).
