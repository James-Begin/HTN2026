"""Client for Sequitor's custom Baseten OpenJev claim reranker.

The deployed Truss accepts a batch of ``{reference, candidate}`` pairs.  The
adapter deliberately understands both the original symmetric-NLI response and
the fine-tuned five-class response, so the live service can move to the
fine-tuned deployment without another API contract change.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class OpenJevReranker:
    def __init__(self, api_key: str, endpoint: str) -> None:
        if not api_key or not endpoint:
            raise ValueError("OpenJev key or endpoint unavailable")
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not re.fullmatch(r"model-[a-z0-9]+\.api\.baseten\.co", parsed.hostname or "")
                or not re.fullmatch(r"/(?:production|deployment/[a-z0-9]+)/predict", parsed.path)
                or parsed.query or parsed.fragment):
            raise ValueError("Invalid OpenJev Baseten endpoint")
        self._key = api_key
        self._endpoint = endpoint
        self.model_id = parsed.hostname.split(".", 1)[0][6:]

    def score(self, reference: str, posts: list[dict], emit=None) -> dict:
        """Annotate retrieved posts with a claim-equivalence score and register."""
        candidates = [post for post in posts if str(post.get("text") or "").strip()][:128]
        if not candidates:
            return {"status": "openjev", "model": self.model_id, "reranked": 0}
        if emit:
            emit("stage", {"name": "Ranking claims with fine-tuned OpenJev"})
        pairs = [{"id": str(post.get("id") or index), "reference": reference[:1000],
                  "candidate": str(post["text"])[:1000]}
                 for index, post in enumerate(candidates)]
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps({"pairs": pairs}).encode(),
            headers={"Authorization": "Api-Key " + self._key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenJev HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("OpenJev request failed") from exc

        rows = payload.get("results")
        if not isinstance(rows, list) or len(rows) != len(candidates):
            raise RuntimeError("OpenJev response did not match the request")
        annotated = []
        for post, row in zip(candidates, rows):
            if not isinstance(row, dict):
                raise RuntimeError("OpenJev result was invalid")
            score = row.get("same_claim_prob", row.get("same_claim"))
            if not isinstance(score, (int, float)):
                raise RuntimeError("OpenJev result was missing same-claim probability")
            post["sameClaimScore"] = round(max(0.0, min(1.0, float(score))), 5)
            register = row.get("predicted_label")
            if not isinstance(register, str):
                distribution = row.get("distribution")
                if isinstance(distribution, dict) and distribution:
                    register = max(distribution, key=distribution.get)
            if isinstance(register, str) and register:
                post["sameClaimRegister"] = register[:40]
            post["rerankerModel"] = "OpenJev " + self.model_id
            annotated.append(post)
        result = {"status": "openjev", "model": self.model_id, "reranked": len(annotated),
                  "method": str(payload.get("method") or "five-class claim reranker")}
        if emit:
            emit("posts.upsert", {"posts": annotated})
            emit("model.ready", {"model": result})
        return result
