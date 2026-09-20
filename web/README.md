# Sequitor UI

React + Three.js frontend. Entry point is `src/main.tsx` → `DarioDemo.tsx`.

From the repo root:

```bash
cd web && npm ci && npm run dev
```

Needs `python3 sequitor_server.py` on port 8765 (`/api` is proxied). Production builds are served by that same Python process after `npm run build`.
