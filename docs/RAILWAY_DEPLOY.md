# Railway live interface

The repository now contains a multistage `Dockerfile` that builds React and serves the built site from the Python API on Railway's `PORT`. One Railway service is enough: the browser and `/api/*` share an origin, so live SSE works without exposing provider keys in JavaScript.

## Deploy

1. Sign in to Railway and create a project with a service from `James-Begin/HTN2026`, branch `main`, repository root `/`. Railway detects the root `Dockerfile`; `railway.json` sets `/api/health` as the deploy health check.
2. Attach **one persistent volume mounted at `/data`** to that service before entering X credentials. Railway exposes `RAILWAY_VOLUME_MOUNT_PATH`, which Sequitor uses for `sequitor-cache.json` and SSE event logs. The server refuses to start on Railway without that volume so a restart cannot reset the spend ledger.
3. Set service variables `X_BEARER`, `OPENAI_API_KEY`, and `BASETEN_API_KEY`. Optional model routes: `SEQUITOR_BASETEN_EMBED_URL`, `SEQUITOR_BASETEN_EMBED_MODEL`, `SEQUITOR_BASETEN_CHAIN_URL`, and `SEQUITOR_JEV_RERANK_URL`. The Jev route must be the custom Truss production URL ending in `/production/predict`. When healthy, it provides the `sameClaimScore` and five-class register; the Chain continues to add response roles and observed X edges. Keep all keys in Railway variables; `.env` stays local and ignored.
4. Generate a public domain in the service's Networking settings. Open `/api/health` and confirm the X, OpenAI, and Baseten flags are true, then open `/`. The **Explore live** field appears when the same-origin API responds. Enter a post URL or short claim and watch the chart and posts arrive.

The default server-wide cap is 1,800 X post reads plus 48 counts calls, roughly $9.48. It can be changed with `SEQUITOR_X_POST_CAP` and `SEQUITOR_X_COUNTS_CAP`, but the cap applies to the persistent Railway ledger, not the local testing ledger. X billing is account-wide, so include local testing spend when deciding the remote cap. Use one Railway replica with the mounted volume for this hackathon demo.

The GitHub Pages URL remains an offline recorded demo. The Railway URL is the full live interface. Since the Railway account is not authenticated on this machine yet, the service and its public domain still require account sign-in and creation.
