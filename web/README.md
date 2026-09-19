# Sequitor browser

The current entry point is `src/Sequitor.tsx`. It opens a saved measurement from X, then lets you select a UTC day, rank retrieved posts by captured likes or recency, and inspect recorded quote/reply context. The local API adds a bounded live path using OpenAI for search planning, X for source records and counts, and Baseten for reaction curation.

From the repository root, start the one-URL demo:

```bash
cd web && npm ci && npm run build
cd .. && python3 sequitor_server.py
```

Open <http://127.0.0.1:8765>. For hot reload, run the Python server and `npm run dev` in separate terminals; Vite proxies `/api`. Credentials belong only in the ignored root `.env` file. The public npm lockfile works with `npm ci`.

To create a portable saved demo, run `npm run build:offline`. This writes `dist/sequitor-offline.html` with the recorded run, styles, fonts, and JavaScript in one file. It cannot run new live searches without the Python server. External post links still require a network connection.

The `App.tsx` and playback files remain in the tree as the earlier Claimtrace prototype; they are no longer the browser entry point. See the root README and `SEQUITOR_HANDOFF.md` for current scope, limits, and release status.
