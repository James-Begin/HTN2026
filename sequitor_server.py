"""Small, bounded demo API for Sequitor. Run with `python3 sequitor_server.py`.

Only the server reads provider keys. Search results and spend counters are cached in
work/sequitor-cache.json, which is deliberately excluded from Git.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from claimtrace.baseten import CrossEncoder, HostedLLM
from claimtrace.resolve import resolve
from claimtrace.xapi import XClient, now_safe
from sequitor_baseten_chain import BasetenChainClient

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SEQUITOR_DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or ROOT / "work")
CACHE_FILE = DATA_DIR / "sequitor-cache.json"
CAPTURE_FILE = ROOT / "demo" / "recordings" / "sequitor-live.json"
DARIO_HUMOR_FILE = ROOT / "demo" / "recordings" / "dario-humor.json"
SNAPSHOT_FILE = ROOT / "demo" / "recordings" / "pace-the-frontier" / "snapshot.json"
EVENT_DIR = DATA_DIR / "sequitor-streams"
DEFAULT_SEED = "https://x.com/DarioAmodei/status/2098773920774074715"
MAX_POSTS = 600  # $3.00 at the default cap.
MAX_COUNTS = 20  # $0.20 at the default cap.


class StoppedRun(Exception):
    pass


class StreamJob:
    """Small durable event log. A reconnect never starts provider work again."""

    def __init__(self, job_id: str, events: list[dict] | None = None) -> None:
        self.id = job_id
        self.events = events or []
        self.condition = threading.Condition()
        self.stopped = False
        self.done = bool(self.events and self.events[-1]["type"] in
                         {"run.completed", "run.failed", "run.stopped"})

    def emit(self, kind: str, payload: dict) -> None:
        with self.condition:
            if self.stopped and kind not in {"run.stopped", "run.failed"}:
                raise StoppedRun()
            event = {"runId": self.id, "sequence": len(self.events) + 1,
                     "type": kind, "at": today_utc(), "payload": payload}
            EVENT_DIR.mkdir(parents=True, exist_ok=True)
            with (EVENT_DIR / (self.id + ".jsonl")).open("a") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.events.append(event)
            if kind in {"run.completed", "run.failed", "run.stopped"}:
                self.done = True
            self.condition.notify_all()


class StreamHub:
    def __init__(self) -> None:
        self.jobs: dict[str, StreamJob] = {}
        self.lock = threading.Lock()

    def get(self, job_id: str) -> StreamJob | None:
        with self.lock:
            if job_id in self.jobs:
                return self.jobs[job_id]
            if not re.fullmatch(r"[0-9a-f]{32}", job_id):
                return None
            path = EVENT_DIR / (job_id + ".jsonl")
            if not path.is_file():
                return None
            events = [json.loads(line) for line in path.read_text().splitlines() if line]
            job = StreamJob(job_id, events)
            if not job.done:
                job.emit("run.failed", {"message": "The server restarted during this investigation. Existing results remain available."})
            self.jobs[job_id] = job
            return job

    def start(self, seed: str, mode: str) -> StreamJob:
        job = StreamJob(uuid.uuid4().hex)
        with self.lock:
            self.jobs[job.id] = job

        def work() -> None:
            try:
                job.emit("run.started", {"source": "recorded" if mode == "recorded" else "live",
                                         "seed": seed})
                if mode == "recorded":
                    recorded = recorded_demo()
                    job.emit("run.ready", pending_activity(recorded, "recorded"))
                    posts = sorted(recorded.get("posts", []),
                                   key=lambda post: -(post.get("likes") or 0))
                    buckets = recorded.get("buckets", [])
                    # Bars arrive first. The visible posts and then the map fill
                    # progressively instead of jumping to the completed capture.
                    first = max(len(buckets), min(10, len(posts)) * 6)
                    for tick in range(first):
                        if tick < len(buckets):
                            job.emit("buckets.upsert", {"bucket": buckets[tick]})
                        if tick % 6 == 0 and tick // 6 < min(10, len(posts)):
                            job.emit("posts.upsert", {"posts": [posts[tick // 6]]})
                        time.sleep(0.14)
                    for index in range(10, len(posts), 3):
                        job.emit("posts.upsert", {"posts": posts[index:index + 3]})
                        time.sleep(0.14)
                    job.emit("run.completed", {"model": recorded.get("model"),
                                               "rankingCoverage": recorded.get("rankingCoverage"),
                                               "xSpend": recorded.get("xSpend", 0)})
                    return
                with APP.lock:
                    result = APP.explore(seed, emit=job.emit)
                job.emit("run.completed", {"model": result.get("model"),
                                           "rankingCoverage": result.get("rankingCoverage"),
                                           "xSpend": result.get("xSpend", 0)})
            except StoppedRun:
                job.emit("run.stopped", {})
            except Exception as exc:
                job.emit("run.failed", {"message": str(exc)[:180],
                                        "reason": type(exc).__name__})

        threading.Thread(target=work, daemon=True).start()
        return job


STREAMS = StreamHub()


def load_local_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value)


load_local_env()
MAX_POSTS = int(os.environ.get("SEQUITOR_X_POST_CAP", MAX_POSTS))
MAX_COUNTS = int(os.environ.get("SEQUITOR_X_COUNTS_CAP", MAX_COUNTS))


def read_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def today_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pending_activity(run: dict, source: str) -> dict:
    """Keep chart slots stable while their measured counts arrive as events."""
    buckets = run.get("buckets", [])
    return {**run, "kind": "saved" if source == "recorded" else run.get("kind", "live"),
            "posts": [], "savedPeriods": {}, "streamSource": source,
            "activityScaleMax": max((bucket.get("count", 0) for bucket in buckets), default=1),
            "buckets": [{**bucket, "count": 0, "pending": True} for bucket in buckets]}


def emit_activity(emit, run: dict, source: str, pause: float = 0.08) -> None:
    if not emit:
        return
    emit("run.ready", pending_activity(run, source))
    for bucket in run.get("buckets", []):
        emit("buckets.upsert", {"bucket": bucket})
        time.sleep(pause)


def emit_post_batches(emit, posts: list[dict], size: int = 10, pause: float = 0.025) -> None:
    """Pace a returned X page briefly so the browser can paint between updates."""
    if not emit:
        return
    for index in range(0, len(posts), size):
        emit("posts.upsert", {"posts": posts[index:index + size]})
        if index + size < len(posts):
            time.sleep(pause)


def emit_progressive_posts(emit, posts: list[dict]) -> None:
    """Let the first screen populate one post at a time, then fill the remainder."""
    if not emit:
        return
    for post in posts[:10]:
        emit("posts.upsert", {"posts": [post]})
        time.sleep(0.11)
    emit_post_batches(emit, posts[10:], size=10, pause=0.06)


def day_bounds(day: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return start, min(start + timedelta(days=1), now_safe())


def phrase(raw: str) -> str:
    """A model may suggest words, never raw X operators."""
    words = re.findall(r"[\w'-]+", raw, flags=re.UNICODE)[:7]
    if len(words) < 2:
        raise ValueError("Search phrase needs at least two words")
    return '"' + " ".join(words) + '"'


def terms(raw: str) -> str:
    """A conservative unquoted discovery query using X's implicit AND."""
    words = [word for word in re.findall(r"[\w'-]+", raw, flags=re.UNICODE)
             if word.casefold() not in {"ai", "the", "and", "industry", "third-party"}][:2]
    if len(words) < 2:
        raise ValueError("Discovery query needs at least two words")
    return " ".join(words)


def context_count_query(plan: dict) -> str:
    """A distinctive unquoted count query when the literal seed phrase has no hits."""
    entity = str((plan.get("entities") or [""])[0])
    anchor = re.findall(r"[\w'-]+", entity, flags=re.UNICODE)[:2]
    phrase_words = re.findall(r"[\w'-]+", plan.get("volumePhrase") or "", flags=re.UNICODE)
    stop = {"a", "an", "the", "is", "are", "was", "were", "will", "has", "have", "opening", "opened", "about", "how"}
    distinctive = [word for word in phrase_words if word.casefold() not in stop
                   and word.casefold() not in {part.casefold() for part in anchor}]
    return " ".join((anchor + distinctive[-2:])[:4])


def distinct_queries(values: list[str], limit: int = 2) -> list[str]:
    """Keep model-generated discovery bounded and compatible with X implicit AND."""
    queries: list[str] = []
    for value in values:
        try:
            query = terms(value)
        except (TypeError, ValueError):
            continue
        if query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
        if len(queries) >= limit:
            break
    return queries


def normalized_words(text: str) -> set[str]:
    return {word.casefold() for word in re.findall(r"[\w'-]{3,}", text, flags=re.UNICODE)
            if word.casefold() not in {"the", "and", "that", "with", "this", "from", "have", "will", "about", "your"}}


def token_overlap(left: str, right: str) -> float:
    a, b = normalized_words(left), normalized_words(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def cosine(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else None


def post_from_x(row: dict, scope: str) -> dict:
    refs = row.get("referenced_tweets") or []
    metrics = row.get("public_metrics") or {}
    user = row.get("sequitor_author") or {}
    return {
        "id": str(row["id"]), "text": row.get("text") or "",
        "publishedAt": row.get("created_at") or "", "authorId": str(row.get("author_id") or ""),
        "handle": user.get("username") or "", "author": user.get("name") or "X post",
        "avatar": user.get("profile_image_url"), "likes": metrics.get("like_count"),
        "reposts": metrics.get("retweet_count"), "replies": metrics.get("reply_count"),
        "url": f"https://x.com/i/status/{row['id']}",
        "parentId": next((str(ref["id"]) for ref in refs if ref.get("type") == "replied_to"), None),
        "quotedPostId": next((str(ref["id"]) for ref in refs if ref.get("type") == "quoted"), None),
        "scope": scope, "captureTime": today_utc(), "textIsExcerpt": False,
    }


def post_from_snapshot(row: dict) -> dict:
    return {
        "id": str(row["id"]), "text": row["text"], "publishedAt": row["publishedAt"],
        "authorId": row.get("authorId") or "", "handle": row.get("handle") or "",
        "author": (row.get("author") or "X post").split(" · @", 1)[0],
        "likes": row.get("likes"),
        "url": row["url"], "parentId": None, "quotedPostId": row.get("quotedPostId"),
        "scope": "saved source", "captureTime": row["capture"]["capturedAt"],
        "textIsExcerpt": row["capture"].get("textIsExcerpt", False),
    }


def sample_demo() -> dict:
    saved = read_json(SNAPSHOT_FILE, {})
    posts = [post_from_snapshot(row) for row in saved.get("posts", [])]
    days = sorted({post["publishedAt"][:10] for post in posts})
    buckets = [{"day": day, "count": sum(p["publishedAt"].startswith(day) for p in posts),
                "coverage": "sample"} for day in days]
    return {
        "id": "frontier-saved", "seed": DEFAULT_SEED, "title": "We Must Pace the Frontier",
        "kind": "saved", "capturedAt": saved.get("capturedAt"), "scope": "Seven selected saved X posts",
        "query": None, "buckets": buckets, "posts": posts, "selectedDay": "2026-09-12",
        "rankingCoverage": "selected saved sources only", "searchPlan": None,
        "model": {"openai": "not run in saved sample", "baseten": "not run in saved sample"},
        "note": "This is a selected source sample. Its bar heights count saved posts, not X-wide activity.",
        "xSpend": 0,
    }


def recorded_demo() -> dict:
    """Add a separately sourced humor branch without rewriting the old capture."""
    recorded = read_json(CAPTURE_FILE, sample_demo())
    supplement = read_json(DARIO_HUMOR_FILE, {"posts": []})
    posts = supplement.get("posts") or []
    if not posts:
        return recorded
    saved_periods = recorded.setdefault("savedPeriods", {})
    for post in posts:
        day = post["publishedAt"][:10]
        period = saved_periods.get(day)
        if period:
            period["posts"] = list({row["id"]: row for row in period.get("posts", []) + [post]}.values())
        if day == recorded["selectedDay"]:
            recorded["posts"] = list({row["id"]: row for row in recorded.get("posts", []) + [post]}.values())
    recorded["note"] = (recorded.get("note") or "") + " Three later targeted humor-search posts are included with their own capture timestamps."
    return recorded


class Sequitor:
    def __init__(self) -> None:
        load_local_env()
        self.lock = threading.Lock()
        self.cache = read_json(CACHE_FILE, {"runs": {}, "periods": {}, "ledger": {}})
        self.cache.setdefault("runs", {})
        self.cache.setdefault("periods", {})
        self.cache.setdefault("ledger", {})
        self.cache.setdefault("embeddings", {})
        self._cross_encoder_unavailable = False
        self.x = XClient(os.environ.get("X_BEARER", ""), post_budget=MAX_POSTS) if os.environ.get("X_BEARER") else None
        if self.x:
            self.x.posts_read = int(self.cache["ledger"].get("postsRead", 0))
            self.x.counts_calls = int(self.cache["ledger"].get("countsCalls", 0))

    def save(self) -> None:
        if self.x:
            self.cache["ledger"] = {"postsRead": self.x.posts_read,
                                    "countsCalls": self.x.counts_calls,
                                    "estimatedXSpend": round(self.x.spend, 3)}
        write_json(CACHE_FILE, self.cache)

    def count(self, query: str, start: datetime, end: datetime) -> list[dict]:
        if not self.x or self.x.counts_calls >= MAX_COUNTS:
            raise RuntimeError("X counts budget reached or bearer token unavailable")
        buckets, token = self.x.counts(query, start, end)
        self.save()
        if token:
            # One demo window is at most 30 days; never pretend a truncated series is complete.
            for bucket in buckets:
                bucket["sequitor_partial"] = True
        return buckets

    def search(self, query: str, day: str, limit: int = 50, scope: str = "measured phrase") -> tuple[list[dict], bool]:
        if not self.x:
            raise RuntimeError("X bearer token unavailable")
        start, end = day_bounds(day)
        if start >= end:
            return [], False
        available = MAX_POSTS - self.x.posts_read
        if available < 10:
            raise RuntimeError("X post budget reached for this demo server")
        take = min(limit, available)
        try:
            rows, next_token = self.x.search(query + " -is:retweet", start, end, max_results=take)
        finally:
            self.save()
        return [post_from_x(row, scope) for row in rows], bool(next_token)

    def openai_plan(self, text: str) -> dict:
        """Create a small, inspectable context card before any X search."""
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OpenAI API key unavailable")
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "context_label": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "string"}},
                "angles": {"type": "array", "items": {"type": "string"}},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "volume_phrase": {"type": "string"},
                "discovery_queries": {"type": "array", "items": {"type": "string"}},
                "why_discovery": {"type": "string"},
            },
            "required": ["context_label", "entities", "angles", "uncertainties",
                         "volume_phrase", "discovery_queries", "why_discovery"],
        }
        body = {
            "model": "gpt-4.1-mini",
            "instructions": (
                "Build an evidence-bounded context card for exploring discussion around an X post. "
                "context_label must be a neutral 3–10 word description, not a truth claim. "
                "entities are only names or organizations grounded in the post. angles are possible "
                "discussion directions, not facts. uncertainties must say what the post alone cannot establish. "
                "volume_phrase must be 2–6 consecutive words copied from the post for a measured histogram. "
                "discovery_queries contains at most two 2–3 word, unquoted search term groups likely to find "
                "posts about the same event that do not repeat the volume phrase. Prefer a name plus a distinctive "
                "concept. Do not add X operators, invent quotations, or state that a rumor is true."
            ),
            "input": text[:3000],
            "text": {"format": {"type": "json_schema", "name": "sequitor_search_plan",
                                "strict": True, "schema": schema}},
            "max_output_tokens": 250,
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            data = json.load(response)
        content = next((part.get("text") for item in data.get("output", [])
                        for part in item.get("content", []) if part.get("type") == "output_text"), None)
        if not content:
            raise RuntimeError("OpenAI returned no search plan")
        plan = json.loads(content)
        primary = phrase(plan["volume_phrase"])
        if primary.strip('"').casefold() not in text.casefold():
            raise RuntimeError("OpenAI's measured phrase was not in the seed post")
        discovery = distinct_queries(plan.get("discovery_queries") or [])
        return {"planVersion": 4, "contextLabel": str(plan["context_label"])[:110],
                "entities": [str(item)[:50] for item in plan["entities"][:6]],
                "angles": [str(item)[:70] for item in plan["angles"][:4]],
                "uncertainties": [str(item)[:110] for item in plan["uncertainties"][:3]],
                "volumePhrase": primary, "discoveryPhrase": discovery[0] if discovery else None,
                "discoveryQueries": discovery, "expansionQueries": [],
                "whyDiscovery": str(plan["why_discovery"])[:200], "model": data.get("model")}

    def expand_context(self, plan: dict, seed_text: str, posts: list[dict]) -> dict:
        """One grounded expansion round. It never sees an unbounded X corpus."""
        key = os.environ.get("OPENAI_API_KEY")
        if not key or not posts:
            return {"queries": [], "reason": ""}
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {"queries": {"type": "array", "items": {"type": "string"}},
                           "reason": {"type": "string"}},
            "required": ["queries", "reason"],
        }
        evidence = [{"id": post["id"], "scope": post.get("scope"), "text": post.get("text", "")[:240]}
                    for post in sorted(posts, key=lambda post: -(post.get("rankingScore") or 0))[:12]]
        body = {
            "model": "gpt-4.1-mini",
            "instructions": (
                "Suggest at most two new, unquoted 2–3 term X discovery queries. Base them only on the seed, "
                "the supplied context card, and retrieved posts. Seek a missing facet or alternate wording rather "
                "than repeating an existing query. Do not add X operators, claim truth, infer a source, or use "
                "generic terms alone. Return an empty list when the evidence is already repetitive."
            ),
            "input": json.dumps({"seed": seed_text[:700], "context": plan.get("contextLabel"),
                                  "entities": plan.get("entities", []), "existingQueries": plan.get("discoveryQueries", []),
                                  "posts": evidence}, ensure_ascii=False),
            "text": {"format": {"type": "json_schema", "name": "sequitor_context_expansion",
                                "strict": True, "schema": schema}},
            "max_output_tokens": 180,
        }
        req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as response:
            data = json.load(response)
        content = next((part.get("text") for item in data.get("output", [])
                        for part in item.get("content", []) if part.get("type") == "output_text"), None)
        if not content:
            raise RuntimeError("OpenAI returned no context expansion")
        result = json.loads(content)
        known = {str(query).casefold() for query in plan.get("discoveryQueries", [])}
        queries = [query for query in distinct_queries(result.get("queries") or []) if query.casefold() not in known]
        return {"queries": queries, "reason": str(result.get("reason") or "")[:180], "model": data.get("model")}

    def embed_texts(self, texts: list[str]) -> tuple[list[list[float] | None], str]:
        """Use an optional Baseten BEI endpoint; retain a clear local fallback until it exists."""
        endpoint = os.environ.get("SEQUITOR_BASETEN_EMBED_URL", "").rstrip("/")
        key = os.environ.get("BASETEN_API_KEY")
        model = os.environ.get("SEQUITOR_BASETEN_EMBED_MODEL", "not-required")
        if not endpoint or not key:
            return [None] * len(texts), "token-overlap fallback"
        # Keep vectors tied to the deployment as well as the model label: two
        # Baseten deployments can legitimately expose the same model name.
        deployment = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
        cached = self.cache.setdefault("embeddings", {}).setdefault(deployment, {}).setdefault(model, {})
        hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        missing = [index for index, digest in enumerate(hashes) if digest not in cached]
        for offset in range(0, len(missing), 64):
            indices = missing[offset:offset + 64]
            body = {"input": [texts[index][:3000] for index in indices], "model": model}
            req = urllib.request.Request(endpoint + "/embeddings", data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as response:
                payload = json.load(response)
            rows = payload.get("data") or []
            if len(rows) != len(indices):
                raise RuntimeError("Baseten embedding response did not match the request")
            for index, row in zip(indices, rows):
                vector = row.get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("Baseten embedding response was missing a vector")
                cached[hashes[index]] = vector
        self.save()
        return [cached.get(digest) for digest in hashes], "Baseten embeddings"

    def rank_posts(self, seed: dict, posts: list[dict]) -> dict:
        """Stable hybrid scoring now; a future trained reranker simply supplies one signal."""
        if not posts:
            return {"status": "no posts", "semantic": None, "reranker": "not available"}
        try:
            vectors, semantic_method = self.embed_texts([seed.get("text", "")] + [post.get("text", "") for post in posts])
        except Exception as exc:
            vectors, semantic_method = [None] * (len(posts) + 1), "token-overlap fallback"
            embedding_error = type(exc).__name__
        else:
            embedding_error = None
        seed_vector = vectors[0]
        seed_id = str(seed.get("id") or "")
        for post, vector in zip(posts, vectors[1:]):
            lexical = token_overlap(seed.get("text", ""), post.get("text", ""))
            semantic = cosine(seed_vector, vector)
            if semantic is None:
                semantic = lexical
            relation = 1.0 if seed_id and (post.get("parentId") == seed_id or post.get("quotedPostId") == seed_id) else 0.0
            scope = 1.0 if post.get("scope") in {"direct conversation", "context expansion"} else .6 if post.get("scope") == "broader discovery" else .35
            reranker = post.get("sameClaimScore")
            score = (.45 * float(reranker) + .25 * semantic + .18 * lexical + .08 * relation + .04 * scope) if reranker is not None \
                else (.52 * semantic + .25 * lexical + .18 * relation + .05 * scope)
            post["semanticScore"] = round(semantic, 4)
            post["lexicalScore"] = round(lexical, 4)
            post["rankingScore"] = round(score, 4)
            post["rankingMethod"] = "hybrid + trained reranker" if reranker is not None else "hybrid retrieval"
        return {"status": "ready", "semantic": semantic_method,
                "reranker": "connected" if any(post.get("sameClaimScore") is not None for post in posts) else "awaiting trained endpoint",
                **({"embeddingError": embedding_error} if embedding_error else {})}

    def classify(self, seed_text: str, posts: list[dict], emit=None) -> dict:
        key = os.environ.get("BASETEN_API_KEY")
        if not key or not posts:
            return {"status": "unavailable", "model": None}
        chain_url = os.environ.get("SEQUITOR_BASETEN_CHAIN_URL", "").strip()
        if chain_url:
            try:
                return BasetenChainClient(key, chain_url).classify(seed_text, posts, emit=emit)
            except Exception as exc:
                if emit:
                    emit("stage", {"name": "Baseten Chain unavailable; using hosted curation",
                                   "reason": type(exc).__name__})
        if not self._cross_encoder_unavailable:
            try:
                scorer = CrossEncoder(key)
                scores = scorer.score(seed_text[:1000], [p["text"][:1000] for p in posts[:32]], want_dist=True)
                for post, score, distribution in zip(posts, scores, scorer.last_distributions):
                    post["sameClaimScore"] = round(score, 4)
                    post["sameClaimRegister"] = max(distribution, key=distribution.get) if distribution else None
                return {"status": "dedicated cross-encoder", "model": "q9p28o63", "pairs": len(scores)}
            except Exception:
                # The archived deployment is unavailable. Retry only after restart.
                self._cross_encoder_unavailable = True
        try:
            model = "openai/gpt-oss-120b"
            llm = HostedLLM(key, model=model)
            ranked = sorted(posts, key=lambda p: -(p.get("likes") or 0))
            branch = [p for p in ranked if p.get("scope") in ("direct conversation", "broader discovery")]
            candidates = list({p["id"]: p for p in (ranked[:6] + branch[:6])}.values())[:12]
            payload = [{"id": p["id"], "text": p["text"][:190]} for p in candidates]
            answer = llm.json_call(
                "Pick at most three posts worth exploring from this conversation. Return JSON only: "
                "{'picks':[{'id':'exact provided id','kind':'same wording or reaction or criticism "
                "or question or joke'}]}. Prefer a meaningful range of responses over three near "
                "duplicates. Do not infer copying, truth, or an unobserved social relationship.",
                json.dumps({"seed": seed_text[:450], "posts": payload}), max_tokens=650,
            )
            kinds = {str(row.get("id")): row.get("kind") for row in answer.get("picks", [])
                     if isinstance(row, dict)}
            allowed = {"same wording", "reaction", "criticism", "question", "joke"}
            for post in posts:
                if kinds.get(post["id"]) in allowed:
                    post["basetenKind"] = kinds[post["id"]]
                    post["basetenPick"] = True
            return {"status": "hosted curation", "model": model,
                    "classified": sum(bool(p.get("basetenPick")) for p in posts)}
        except Exception as exc:
            return {"status": "unavailable", "model": None, "reason": type(exc).__name__}

    def period(self, run_id: str, day: str, emit=None) -> dict:
        run = self.cache["runs"].get(run_id)
        if not run:
            raise ValueError("Run not found")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid UTC day")
        key = run_id + ":" + day
        if key in self.cache["periods"] and self.cache["periods"][key].get("schemaVersion") == 4 and self.cache["periods"][key].get("discoveryQuery") == run["searchPlan"].get("discoveryPhrase"):
            cached_period = self.cache["periods"][key]
            if emit:
                emit("stage", {"name": "Loading cached posts", "source": "cache"})
                ordered = sorted(cached_period["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_post_batches(emit, ordered, size=16, pause=0.035)
            status = cached_period.get("model", {}).get("status")
            if status == "unavailable" or (os.environ.get("SEQUITOR_BASETEN_CHAIN_URL") and status != "baseten chain"):
                cached_period["model"] = self.classify(run["seedPost"]["text"], cached_period["posts"], emit=emit)
                run["posts"] = cached_period["posts"]
                run["model"] = {"openai": run["searchPlan"].get("model"), "baseten": cached_period["model"]}
                self.save()
                if run.get("seed") == DEFAULT_SEED:
                    write_json(CAPTURE_FILE, run)
            if any("rankingScore" not in post for post in cached_period["posts"]):
                retrieval = self.rank_posts(run["seedPost"], cached_period["posts"])
                cached_period["model"] = {**cached_period.get("model", {}), "retrieval": retrieval}
                self.save()
            current_spend = round(self.x.spend, 3) if self.x else 0
            cached_period["xSpend"] = current_spend
            run["xSpend"] = current_spend
            run.setdefault("savedPeriods", {})[day] = cached_period
            self.save()
            if run.get("seed") == DEFAULT_SEED:
                write_json(CAPTURE_FILE, run)
            return cached_period
        prior = self.cache["periods"].get(key)
        if prior:
            primary = [p for p in prior["posts"] if p.get("scope") == "measured phrase"]
            partial = prior.get("partial", False)
        else:
            if emit:
                emit("stage", {"name": "Retrieving phrase matches"})
            primary, partial = self.search(run["query"], day,
                                           limit=70 if day == run["selectedDay"] else 40)
        if emit and primary:
            emit_progressive_posts(emit, sorted(primary, key=lambda post: -(post.get("likes") or 0)))
        # Initial context-card queries create explicitly-labelled branches outside
        # the chart's literal phrase scope.
        secondary, extra_partial = [], False
        initial_queries = run["searchPlan"].get("discoveryQueries") or ([run["searchPlan"].get("discoveryPhrase")] if run["searchPlan"].get("discoveryPhrase") else [])
        if day == run["selectedDay"] and initial_queries:
            if emit:
                emit("stage", {"name": "Searching the first context branches"})
            for query in initial_queries[:2]:
                if query == run["query"]:
                    continue
                rows, partial_result = self.search(query, day, limit=30, scope="broader discovery")
                secondary.extend(rows)
                extra_partial = extra_partial or partial_result
                if emit and rows:
                    emit_post_batches(emit, rows)
        unique = {p["id"]: p for p in primary}
        if prior:
            for post in prior["posts"]:
                unique.setdefault(post["id"], post)
        for post in secondary:
            unique.setdefault(post["id"], post)
        seed_id = str(run.get("seedPost", {}).get("id") or "")
        if day == run["selectedDay"] and seed_id.isdigit() and not (prior and prior.get("schemaVersion", 0) >= 2):
            try:
                if emit:
                    emit("stage", {"name": "Reading direct conversation"})
                conversation, conv_partial = self.search(f"conversation_id:{seed_id}", day,
                                                         limit=60, scope="direct conversation")
                for post in conversation:
                    unique.setdefault(post["id"], post)
                if emit and conversation:
                    emit_post_batches(emit, conversation)
                extra_partial = extra_partial or conv_partial
            except (RuntimeError, urllib.error.HTTPError):
                pass
            if seed_id == "2098773920774074715":
                saved = read_json(SNAPSHOT_FILE, {})
                for row in saved.get("posts", []):
                    if row["publishedAt"].startswith(day):
                        unique.setdefault(str(row["id"]), post_from_snapshot(row))
        # Include the seed even if it does not pass the search's engagement floor.
        if seed_id.isdigit() and day == run["seedPost"]["publishedAt"][:10]:
            unique.setdefault(run["seedPost"]["id"], run["seedPost"])
        posts = list(unique.values())
        retrieval = self.rank_posts(run["seedPost"], posts)
        # A single second round is grounded in retrieved evidence, then capped at
        # two short X queries. This prevents topic drift and surprise X spend.
        if day == run["selectedDay"] and not run["searchPlan"].get("expansionQueries"):
            try:
                if emit:
                    emit("stage", {"name": "Finding missing context from retrieved evidence"})
                expansion = self.expand_context(run["searchPlan"], run["seedPost"]["text"], posts)
                run["searchPlan"]["expansionQueries"] = expansion["queries"]
                run["searchPlan"]["expansionReason"] = expansion["reason"]
                run["searchPlan"]["expansionModel"] = expansion.get("model")
                if emit:
                    emit("context.expanded", {"plan": run["searchPlan"]})
                for query in expansion["queries"]:
                    rows, partial_result = self.search(query, day, limit=25, scope="context expansion")
                    extra_partial = extra_partial or partial_result
                    for post in rows:
                        unique.setdefault(post["id"], post)
                    if emit and rows:
                        emit_post_batches(emit, rows)
                posts = list(unique.values())
                retrieval = self.rank_posts(run["seedPost"], posts)
            except Exception as exc:
                run["searchPlan"]["expansionError"] = type(exc).__name__
                if emit:
                    emit("stage", {"name": "Context expansion unavailable; keeping first-round evidence"})
        if emit:
            emit_post_batches(emit, posts, size=24, pause=0)
            emit("stage", {"name": "Curating retrieved posts with Baseten"})
        model = self.classify(run["seedPost"]["text"], posts, emit=emit)
        retrieval = self.rank_posts(run["seedPost"], posts)
        if emit:
            updates = [post for post in posts if post.get("basetenPick") or post.get("sameClaimScore") is not None or post.get("rankingScore") is not None]
            emit_post_batches(emit, updates, size=12, pause=0)
            emit("model.ready", {"model": {**model, "retrieval": retrieval}})
        result = {"schemaVersion": 4, "discoveryQuery": run["searchPlan"].get("discoveryPhrase"),
                  "day": day, "posts": posts,
                  "rankingCoverage": "top retrieved posts; search may be truncated" if partial or extra_partial
                  else "top retrieved posts; phrase scope plus one related search",
                  "partial": partial or extra_partial, "model": {**model, "retrieval": retrieval},
                  "xSpend": round(self.x.spend, 3) if self.x else 0}
        self.cache["periods"][key] = result
        if day == run["selectedDay"]:
            run["posts"] = posts
            run["rankingCoverage"] = result["rankingCoverage"]
            run["model"] = {"openai": run["searchPlan"].get("model"), "baseten": model}
        run["xSpend"] = result["xSpend"]
        run["capturedAt"] = today_utc()
        run.setdefault("savedPeriods", {})[day] = result
        self.save()
        if run.get("seed") == DEFAULT_SEED:
            write_json(CAPTURE_FILE, run)
        return result

    def explore(self, seed: str, emit=None) -> dict:
        seed = seed.strip()[:2000]
        if not seed:
            seed = DEFAULT_SEED
        cache_key = re.sub(r"[^a-z0-9]+", "-", seed.lower())[:100]
        if cache_key in self.cache["runs"]:
            cached = self.cache["runs"][cache_key]
            if cached.get("searchPlan", {}).get("planVersion") != 4:
                try:
                    revised = self.openai_plan(cached["seedPost"]["text"])
                    cached["searchPlan"] = revised
                    self.save()
                    self.period(cache_key, cached["selectedDay"])
                except Exception as exc:
                    cached["searchPlan"]["revisionError"] = type(exc).__name__
                    self.save()
            if emit:
                emit_activity(emit, cached, "cache")
                ordered = sorted(cached["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_progressive_posts(emit, ordered)
            current_model = cached.get("model", {}).get("baseten")
            current_status = current_model.get("status") if isinstance(current_model, dict) else current_model
            if os.environ.get("SEQUITOR_BASETEN_CHAIN_URL") and current_status != "baseten chain":
                model = self.classify(cached["seedPost"]["text"], cached["posts"], emit=emit)
                cached["model"] = {**cached.get("model", {}), "baseten": model}
                self.save()
            return cached
        if not self.x:
            raise RuntimeError("X bearer token unavailable")
        original_text = seed
        seed_post = None
        match = re.search(r"/(?:status|statuses)/(\d+)", seed)
        if match:
            if emit:
                emit("stage", {"name": "Resolving the starting post"})
            original = resolve(match.group(1))
            if not original.recoverable_text:
                raise RuntimeError("The seed post's text is unavailable; paste its text instead")
            original_text = original.text
            seed_post = {"id": original.tweet_id, "text": original.text,
                         "publishedAt": original.created_at.isoformat().replace("+00:00", "Z"),
                         "author": "@" + original.handle, "handle": original.handle,
                         "authorId": original.author_id, "likes": original.likes,
                         "avatar": original.avatar or None,
                         "url": f"https://x.com/{original.handle}/status/{original.tweet_id}",
                         "scope": "seed", "captureTime": today_utc(), "textIsExcerpt": False,
                         "quotedPostId": None, "parentId": None}
        if emit:
            emit("seed.resolved", {"post": seed_post, "text": original_text[:2000]})
            emit("stage", {"name": "Planning bounded discovery with OpenAI"})
        try:
            plan = self.openai_plan(original_text)
        except Exception as exc:
            # An OpenAI failure is visible in provenance, never silently counted as API use.
            words = re.findall(r"[\w'-]+", original_text)
            plan = {"planVersion": 4, "contextLabel": "Unstructured seed post",
                    "entities": [], "angles": [], "uncertainties": ["Context planning was unavailable."],
                    "volumePhrase": phrase(" ".join(words[:4])), "discoveryPhrase": None,
                    "discoveryQueries": [], "expansionQueries": [], "whyDiscovery": "",
                    "model": None, "error": type(exc).__name__}
        if emit:
            emit("plan.ready", {"plan": plan})
            emit("stage", {"name": "Measuring phrase activity on X"})
        end = now_safe()
        if seed_post:
            start = max(datetime.fromisoformat(seed_post["publishedAt"].replace("Z", "+00:00")) - timedelta(days=2), end - timedelta(days=28))
        else:
            start = end - timedelta(days=14)
        buckets_raw = self.count(plan["volumePhrase"], start, end)
        buckets = sorted([{"day": row["start"][:10],
                           "count": int(row.get("tweet_count", row.get("post_count", 0))),
                           "coverage": "partial" if row.get("sequitor_partial") else "complete"}
                          for row in buckets_raw], key=lambda row: row["day"])
        measured_phrase = plan["volumePhrase"]
        if not any(bucket["count"] for bucket in buckets):
            fallback_query = context_count_query(plan)
            if fallback_query and fallback_query.casefold() != measured_phrase.strip('"').casefold():
                if emit:
                    emit("stage", {"name": "The exact phrase has no matches; measuring the grounded context"})
                fallback_raw = self.count(fallback_query, start, end)
                buckets = sorted([{"day": row["start"][:10],
                                   "count": int(row.get("tweet_count", row.get("post_count", 0))),
                                   "coverage": "partial" if row.get("sequitor_partial") else "complete"}
                                  for row in fallback_raw], key=lambda row: row["day"])
                plan["volumeFallback"] = fallback_query
                if emit:
                    emit("context.expanded", {"plan": plan})
        if not any(bucket["count"] for bucket in buckets):
            raise RuntimeError("No X activity found for the exact phrase or grounded context query")
        chart_query = plan.get("volumeFallback") or measured_phrase
        peak = max(buckets, key=lambda row: row["count"])
        selected = seed_post["publishedAt"][:10] if seed_post else peak["day"]
        run = {"id": cache_key, "seed": seed, "title": original_text.split("\n")[0][:110],
               "kind": "live", "capturedAt": today_utc(),
               "scope": "X counts for one context query" if plan.get("volumeFallback") else "X counts for one exact phrase",
               "query": chart_query, "buckets": buckets, "posts": [],
               "selectedDay": selected, "rankingCoverage": "not collected yet",
               "searchPlan": plan, "seedPost": seed_post or {"id": "seed-text", "text": original_text,
                                                  "publishedAt": selected + "T00:00:00Z", "author": "Seed text"},
               "model": {"openai": plan.get("model"), "baseten": "pending"},
               "note": (f"The exact phrase {measured_phrase} had no matches. Bars measure the grounded context query {chart_query}. "
                        "The feed includes separately marked discovery branches." if plan.get("volumeFallback") else
                        "Bars measure the exact phrase only. The feed can include separately marked discovery branches."),
               "xSpend": round(self.x.spend, 3)}
        self.cache["runs"][cache_key] = run
        self.save()
        if emit:
            emit_activity(emit, run, "live")
            if seed_post and seed_post["publishedAt"][:10] == selected:
                emit("posts.upsert", {"posts": [seed_post]})
        result = self.period(cache_key, selected, emit=emit)
        run = {**run, "posts": result["posts"], "rankingCoverage": result["rankingCoverage"],
               "model": {"openai": plan.get("model"), "baseten": result["model"]},
               "xSpend": result["xSpend"]}
        self.cache["runs"][cache_key] = run
        self.save()
        if seed == DEFAULT_SEED:
            write_json(CAPTURE_FILE, run)
        return run


APP = Sequitor()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, job: StreamJob) -> None:
        try:
            cursor = max(0, int(self.headers.get("Last-Event-ID") or
                                parse_qs(urlsplit(self.path).query).get("after", ["0"])[0]))
        except ValueError:
            cursor = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                with job.condition:
                    if len(job.events) <= cursor and not job.done:
                        job.condition.wait(timeout=12)
                    events = job.events[cursor:]
                    done = job.done
                for event in events:
                    body = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"id: {event['sequence']}\nevent: sequitor\ndata: {body}\n\n".encode())
                    cursor = event["sequence"]
                if events:
                    self.wfile.flush()
                if done:
                    break
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def _route(self, method: str) -> None:
        url = urlsplit(self.path)
        try:
            if url.path == "/api/health" and method == "GET":
                self._send(200, {"ok": True, "openai": bool(os.environ.get("OPENAI_API_KEY")),
                                 "baseten": bool(os.environ.get("BASETEN_API_KEY")),
                                 "x": bool(APP.x), "xSpend": round(APP.x.spend, 3) if APP.x else 0,
                                 "xPostCap": MAX_POSTS, "xCountsCap": MAX_COUNTS})
                return
            if url.path == "/api/demo" and method == "GET":
                recorded = recorded_demo()
                self._send(200, {**recorded, "kind": "saved"})
                return
            if url.path == "/api/runs" and method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                mode = str(data.get("mode") or "live")
                if mode not in {"live", "recorded"}:
                    raise ValueError("Invalid run mode")
                job = STREAMS.start(str(data.get("seed") or DEFAULT_SEED)[:2000], mode)
                self._send(202, {"runId": job.id, "source": mode,
                                 "eventsUrl": f"/api/runs/{job.id}/events"})
                return
            match = re.fullmatch(r"/api/runs/([0-9a-f]{32})(?:/(events|cancel))?", url.path)
            if match:
                job = STREAMS.get(match.group(1))
                if not job:
                    self._send(404, {"error": "Investigation not found"})
                    return
                action = match.group(2)
                if action == "events" and method == "GET":
                    self._stream(job)
                elif action == "cancel" and method == "POST":
                    with job.condition:
                        job.stopped = True
                    self._send(200, {"ok": True})
                elif action is None and method == "GET":
                    with job.condition:
                        self._send(200, {"runId": job.id, "events": list(job.events),
                                         "done": job.done})
                else:
                    self._send(405, {"error": "Method not allowed"})
                return
            if url.path == "/api/context" and method == "GET":
                post_id = parse_qs(url.query).get("id", [""])[0]
                if not re.fullmatch(r"\d{4,25}", post_id):
                    raise ValueError("Invalid post id")
                found = resolve(post_id)
                if not found.recoverable_text:
                    self._send(404, {"error": "Referenced post unavailable"})
                    return
                self._send(200, {"id": found.tweet_id, "text": found.text,
                                 "publishedAt": found.created_at.isoformat().replace("+00:00", "Z"),
                                 "author": "@" + found.handle, "handle": found.handle,
                                 "authorId": found.author_id, "likes": found.likes,
                                 "avatar": found.avatar or None,
                                 "url": f"https://x.com/{found.handle}/status/{found.tweet_id}",
                                 "scope": "referenced post", "captureTime": today_utc()})
                return
            if url.path == "/api/period" and method == "GET":
                qs = parse_qs(url.query)
                with APP.lock:
                    self._send(200, APP.period(qs.get("run", [""])[0], qs.get("day", [""])[0]))
                return
            if url.path == "/api/explore" and method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                with APP.lock:
                    self._send(200, APP.explore(str(data.get("seed") or "")))
                return
            if url.path.startswith("/api/"):
                self._send(404, {"error": "Unknown API path"})
                return
            # The same server can host the Vite production output for a single URL.
            dist = (ROOT / "web" / "dist").resolve()
            candidate = (dist / url.path.lstrip("/")).resolve()
            if dist not in candidate.parents or not candidate.is_file():
                candidate = dist / "index.html"
            if not candidate.is_file():
                self._send(404, {"error": "Frontend build missing; run npm run build in web/"})
                return
            import mimetypes
            data = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)[:180]})
        except urllib.error.HTTPError as exc:
            self._send(502, {"error": f"Provider HTTP {exc.code}; check service access and the local demo budget"})
        except Exception as exc:
            self._send(502, {"error": str(exc)[:180]})

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def log_message(self, format: str, *args: object) -> None:
        # Do not log user-provided post text or any authorization header.
        if not self.path.startswith("/api/health"):
            super().log_message(format, *args)


if __name__ == "__main__":
    if os.environ.get("RAILWAY_ENVIRONMENT") and not os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        raise RuntimeError("Attach a Railway volume before enabling paid live searches")
    port = int(os.environ.get("PORT") or os.environ.get("SEQUITOR_PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    print(f"Sequitor at http://{host}:{port} (X cap: {MAX_POSTS} posts, {MAX_COUNTS} counts calls)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
