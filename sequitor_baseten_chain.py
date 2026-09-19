"""Gateway adapter for the deployed Sequitor Baseten Chain.

Usage: BasetenChainClient(api_key, chain_url).classify(seed_text, posts, emit)
The Chain analyzes already retrieved posts; this module never calls X.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class BasetenChainClient:
    def __init__(self, api_key: str, chain_url: str) -> None:
        if not api_key or not chain_url:
            raise ValueError("Baseten Chain key or URL unavailable")
        parsed = urlsplit(chain_url)
        if (parsed.scheme != "https" or not re.fullmatch(r"chain-[a-z0-9]+\.api\.baseten\.co", parsed.hostname or "")
                or not parsed.path.endswith("/run_remote") or parsed.query or parsed.fragment):
            raise ValueError("Invalid Baseten Chain endpoint")
        self._key = api_key
        self._url = chain_url
        self.chain_id = parsed.hostname.split(".", 1)[0][6:]

    def classify(self, seed_text: str, posts: list[dict], emit=None) -> dict:
        """Mutate annotated posts and relay Chain progress to the existing SSE log.

        Raises if remote curation did not complete, so callers may use the existing
        local Baseten model fallback without falsely claiming Chain deployment.
        """
        if not posts:
            return {"status": "baseten chain", "model": None, "chainId": self.chain_id,
                    "classified": 0, "observedEdges": 0}
        by_id = {str(post["id"]): post for post in posts if post.get("id")}
        request = urllib.request.Request(
            self._url,
            data=json.dumps({"seed_text": seed_text[:1000],
                             "posts_json": json.dumps(posts[:32])}).encode(),
            headers={"Authorization": "Api-Key " + self._key,
                     "Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        curated = False
        completed = False
        model = None
        candidate_count = 0
        picks_count = 0
        observed_edges = 0
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                lines = []
                for raw in response:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line:
                        if line.startswith("data:"):
                            lines.append(line[5:].lstrip())
                        continue
                    if not lines:
                        continue
                    try:
                        item = json.loads("\n".join(lines))
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Invalid Baseten Chain event") from exc
                    lines = []
                    kind = item.get("type")
                    payload = item.get("payload") or {}
                    if kind == "analysis.started" and emit:
                        emit("stage", {"name": "Analyzing responses with Baseten Chain"})
                    elif kind == "curation.ready":
                        curated = True
                        model = payload.get("model")
                        candidate_count = int(payload.get("candidates") or 0)
                        updates = []
                        for pick in payload.get("picks") or []:
                            post = by_id.get(str(pick.get("id")))
                            if not post:
                                continue
                            post["basetenPick"] = True
                            post["basetenKind"] = str(pick.get("kind") or "")
                            updates.append(post)
                        picks_count = len(updates)
                        if updates and emit:
                            emit("posts.upsert", {"posts": updates})
                    elif kind == "observed.ready":
                        edges = payload.get("edges") or []
                        observed_edges = len(edges)
                        if edges and emit:
                            emit("graph.observed", {"edges": edges, "source": "X referenced_tweets"})
                    elif kind == "analysis.completed":
                        completed = True
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Baseten Chain HTTP {exc.code}") from None
        if not curated or not completed:
            raise RuntimeError("Baseten Chain curation did not complete")
        result = {"status": "baseten chain", "model": model, "chainId": self.chain_id,
                  "classified": picks_count, "candidates": candidate_count,
                  "observedEdges": observed_edges}
        if emit:
            emit("model.ready", {"model": result})
        return result
