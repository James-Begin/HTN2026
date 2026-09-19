"""Baseten Chains entrypoint for Sequitor's post analysis.

The browser does not call this endpoint. The Sequitor gateway sends a bounded batch
of already retrieved posts and relays these SSE events into its durable run stream.
No X credentials or X calls are used in this Chain.
"""
import asyncio
import json
import urllib.request
from typing import AsyncIterator

import truss_chains as chains
from truss.base import truss_config


MODEL = "openai/gpt-oss-120b"
RERANKER_MODEL = "BAAI/bge-reranker-base"
ALLOWED_KINDS = {"same wording", "reaction", "criticism", "question", "joke"}


def _sse(kind: str, payload: dict) -> str:
    return "event: " + kind + "\ndata: " + json.dumps({"type": kind, "payload": payload}, ensure_ascii=False) + "\n\n"


class ConversationCuration(chains.ChainletBase):
    """A Baseten hosted model selects a small, varied set of retrieved posts."""

    remote_config = chains.RemoteConfig(compute=chains.Compute(cpu_count=1, memory="2Gi"))

    def __init__(self, context: chains.DeploymentContext = chains.depends_context()) -> None:
        self._api_key = context.get_baseten_api_key()

    async def run_remote(self, seed_text: str, posts_json: str) -> str:
        posts = json.loads(posts_json)
        ranked = sorted(posts, key=lambda p: -(p.get("likes") or 0))
        branch = [p for p in ranked if p.get("scope") in ("direct conversation", "broader discovery")]
        candidates = list({str(p["id"]): p for p in ranked[:6] + branch[:6]}.values())[:12]
        if not candidates:
            return json.dumps({"model": MODEL, "picks": [], "candidates": 0})
        prompt = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": (
                    "Choose at most three distinct posts worth exploring in this conversation. "
                    "Return a JSON object with picks: [{id, kind}]. IDs must be from the provided list; "
                    "kind must be exactly one of: same wording, reaction, criticism, question, joke. "
                    "Prefer a meaningful range over near duplicates. Do not infer copying, truth, "
                    "an author's identity, or an unobserved social relationship."
                )},
                {"role": "user", "content": json.dumps({
                    "seed": seed_text[:450],
                    "posts": [{"id": str(p["id"]), "text": str(p.get("text") or "")[:190]}
                              for p in candidates],
                })},
            ],
            "response_format": {"type": "json_object"},
            "reasoning_effort": "low",
            "max_tokens": 650,
        }

        def invoke() -> dict:
            request = urllib.request.Request(
                "https://inference.baseten.co/v1/chat/completions",
                data=json.dumps(prompt).encode(),
                headers={"Authorization": "Bearer " + self._api_key,
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=55) as response:
                return json.load(response)

        response = await asyncio.to_thread(invoke)
        content = response["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError("Baseten curation returned no content")
        answer = json.loads(content)
        allowed_ids = {str(p["id"]) for p in candidates}
        picks = []
        for row in answer.get("picks", []):
            if not isinstance(row, dict):
                continue
            post_id, kind = str(row.get("id")), str(row.get("kind"))
            if post_id in allowed_ids and kind in ALLOWED_KINDS and post_id not in {p["id"] for p in picks}:
                picks.append({"id": post_id, "kind": kind})
            if len(picks) == 3:
                break
        return json.dumps({"model": MODEL, "picks": picks, "candidates": len(candidates)})


class ObservedConnections(chains.ChainletBase):
    """Retain only reply/quote edges that X actually supplied."""

    remote_config = chains.RemoteConfig(compute=chains.Compute(cpu_count=1, memory="2Gi"))

    async def run_remote(self, posts_json: str) -> str:
        posts = json.loads(posts_json)
        ids = {str(post["id"]) for post in posts}
        edges = []
        for post in posts:
            source = str(post["id"])
            for field, relation in (("parentId", "reply"), ("quotedPostId", "quote")):
                target = str(post.get(field) or "")
                if target in ids and target != source:
                    edges.append({"source": source, "target": target, "relation": relation,
                                  "provenance": "X referenced_tweets"})
        return json.dumps({"edges": edges, "posts": len(posts)})


class BaselineReranker(chains.ChainletBase):
    """Score seed/post relevance with a compact, public BGE cross-encoder.

    This is intentionally separate from the fine-tuned claim-equivalence model.
    Its sigmoid scores are relevance signals for ranking, never truth, provenance,
    or evidence that an author copied a post.
    """

    remote_config = chains.RemoteConfig(
        compute=chains.Compute(gpu=truss_config.Accelerator.L4, cpu_count=4, memory="12Gi"),
        docker_image=chains.DockerImage(
            # Chain GPU images do not guarantee a framework runtime. Pin the
            # same torch line used by Sequitor's standalone Truss reranker.
            pip_requirements=["torch==2.6.0", "transformers>=4.45,<5", "sentencepiece"],
        ),
    )

    def __init__(self) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL, use_fast=True)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            RERANKER_MODEL, torch_dtype=torch.float16,
        ).eval().to("cuda")

    async def run_remote(self, seed_text: str, posts_json: str) -> str:
        posts = json.loads(posts_json)
        rows = []
        for offset in range(0, len(posts), 16):
            chunk = posts[offset:offset + 16]
            encoded = self._tokenizer(
                [seed_text[:1000]] * len(chunk),
                [str(post.get("text") or "")[:1000] for post in chunk],
                padding=True,
                truncation=True,
                max_length=384,
                return_tensors="pt",
            ).to("cuda")
            with self._torch.inference_mode():
                logits = self._model(**encoded).logits.reshape(-1).float()
                scores = self._torch.sigmoid(logits).cpu().tolist()
            rows.extend({"id": str(post["id"]), "score": round(float(score), 5)}
                        for post, score in zip(chunk, scores))
        return json.dumps({"model": RERANKER_MODEL, "scores": rows, "pairs": len(rows)})


@chains.mark_entrypoint("Sequitor Analysis")
class SequitorAnalysis(chains.ChainletBase):
    """Fan out independent post analysis, streaming each completed result."""

    remote_config = chains.RemoteConfig(compute=chains.Compute(cpu_count=1, memory="2Gi"))

    def __init__(
        self,
        curator: ConversationCuration = chains.depends(ConversationCuration, retries=0),
        observations: ObservedConnections = chains.depends(ObservedConnections),
        reranker: BaselineReranker = chains.depends(BaselineReranker, retries=0),
    ) -> None:
        self._curator = curator
        self._observations = observations
        self._reranker = reranker

    async def run_remote(self, seed_text: str, posts_json: str) -> AsyncIterator[str]:
        posts = json.loads(posts_json)
        bounded = [p for p in posts[:32] if isinstance(p, dict) and p.get("id")]
        bounded_json = json.dumps(bounded)
        yield _sse("analysis.started", {"chain": "Sequitor Analysis", "posts": len(bounded)})

        async def curate() -> tuple[str, dict]:
            return "curation.ready", json.loads(await self._curator.run_remote(seed_text[:1000], bounded_json))

        async def connect() -> tuple[str, dict]:
            return "observed.ready", json.loads(await self._observations.run_remote(bounded_json))

        async def rerank() -> tuple[str, dict]:
            return "rerank.ready", json.loads(await self._reranker.run_remote(seed_text[:1000], bounded_json))

        failed = False
        tasks = [asyncio.create_task(curate()), asyncio.create_task(connect()), asyncio.create_task(rerank())]
        for task in asyncio.as_completed(tasks):
            try:
                kind, payload = await task
                yield _sse(kind, payload)
            except Exception as exc:
                failed = True
                yield _sse("analysis.error", {"reason": type(exc).__name__})
        yield _sse("analysis.completed", {"status": "partial" if failed else "complete",
                                          "chain": "Sequitor Analysis"})
