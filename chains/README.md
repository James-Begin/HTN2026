# Sequitor Baseten Chain

`sequitor_chain.py` is a three-Chainlet analysis pipeline for posts already retrieved by the Sequitor server. `SequitorAnalysis` fans out Baseten hosted-model curation and extraction of X-observed reply/quote edges, then streams each result as SSE. It never fetches from X and does not consume X credits.

The server uses [`sequitor_baseten_chain.py`](../sequitor_baseten_chain.py) as its client adapter. Set `SEQUITOR_BASETEN_CHAIN_URL` to the deployed Chain's `/production/run_remote` endpoint. The adapter is opt-in: if there is no endpoint, keep the server's hosted-model fallback.

Deploy after this Baseten account is allowed to create deployments:

```sh
python3 -m venv work/.venv-baseten
work/.venv-baseten/bin/pip install truss
work/.venv-baseten/bin/truss login --api-key "$BASETEN_API_KEY"
PATH="$PWD/work/.venv-baseten/bin:$PATH" truss chains push chains/sequitor_chain.py --name Sequitor-Analysis --promote --wait
```

Avoid putting the API key in a tracked file. The Chain obtains Baseten's internal key from `DeploymentContext.get_baseten_api_key()`. The request body contains at most 32 already retrieved posts and a seed text. The Chain returns `analysis.started`, `observed.ready`, `curation.ready`, and `analysis.completed` events; each `data:` payload is JSON.

The local dry run is:

```sh
PATH="$PWD/work/.venv-baseten/bin:$PATH" truss chains push chains/sequitor_chain.py --dryrun
```

See [Baseten's Chain deployment guide](https://docs.baseten.co/development/chain/deploy), [invocation guide](https://docs.baseten.co/development/chain/invocation), and [streaming guide](https://docs.baseten.co/development/chain/streaming).
