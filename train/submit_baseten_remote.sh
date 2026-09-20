#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${BASETEN_CTL_VENV:-/tmp/btctl}"
REMOTE="${BASETEN_REMOTE:-baseten}"

if [[ -z "${BASETEN_API_KEY:-}" ]]; then
  echo "BASETEN_API_KEY is required" >&2
  exit 2
fi

if [[ ! -x "$VENV/bin/truss" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet 'truss==0.18.30'
fi

"$VENV/bin/truss" --non-interactive login \
  --api-key "$BASETEN_API_KEY" --remote "$REMOTE" >/dev/null

cd "$ROOT/baseten_remote"
"$VENV/bin/truss" --non-interactive train push config.py \
  --remote "$REMOTE" --job-name sequitor-jev-bge-compare "$@"

echo "Submitted. Monitor with:" >&2
echo "$VENV/bin/truss train view --remote $REMOTE --non-interactive" >&2
