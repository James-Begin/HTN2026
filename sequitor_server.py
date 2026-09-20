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
from claimtrace.xapi import BudgetExceeded, XClient, now_safe
from sequitor_anchor import choose_semantic_anchor, conversation_anchor
from sequitor_baseten_chain import BasetenChainClient
from sequitor_openjev import OpenJevReranker

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SEQUITOR_DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or ROOT / "work")
CACHE_FILE = DATA_DIR / "sequitor-cache.json"
CAPTURE_FILE = ROOT / "demo" / "recordings" / "sequitor-live.json"
DARIO_HUMOR_FILE = ROOT / "demo" / "recordings" / "dario-humor.json"
SNAPSHOT_FILE = ROOT / "demo" / "recordings" / "pace-the-frontier" / "snapshot.json"
EVENT_DIR = DATA_DIR / "sequitor-streams"
DEFAULT_SEED = "https://x.com/DarioAmodei/status/2098773920774074715"
MAX_POSTS = 1800  # $9.00 at the default cap.
MAX_COUNTS = 48   # $0.48 at the default cap.
PLAN_VERSION = 5
ANCHOR_VERSION = 1
ANCHOR_RECORDINGS = {
    "2098435855857668156": ROOT / "demo" / "recordings" / "anchor-tomdale.json",
    "2085392809385988130": ROOT / "demo" / "recordings" / "anchor-drewhahn.json",
    "2098789109980332057": ROOT / "demo" / "recordings" / "anchor-elon-dario.json",
}


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
                    recorded = recording_for_seed(seed)
                    recorded_seed = recorded.get("seedPost")
                    if recorded_seed:
                        payload = {"post": recorded_seed, "text": recorded_seed.get("text", "")[:2000],
                                   "anchorMethod": recorded.get("anchorMethod") or "self",
                                   "anchorHops": recorded.get("anchorHops") or 0}
                        if recorded.get("entryPost") and recorded["entryPost"].get("id") != recorded_seed.get("id"):
                            payload["entryPost"] = recorded["entryPost"]
                        job.emit("seed.resolved", payload)
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
                job.emit("run.failed", {"message": public_run_error(exc)[:240],
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


def optional_x_cap(name: str, default: int) -> int | None:
    """Treat 0 as no Sequitor-side cap; X billing still remains authoritative."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    return None if parsed == 0 else max(10, parsed)


MAX_POSTS = optional_x_cap("SEQUITOR_X_POST_CAP", MAX_POSTS)
MAX_COUNTS = optional_x_cap("SEQUITOR_X_COUNTS_CAP", MAX_COUNTS)


def public_run_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, BudgetExceeded) and message.startswith("X credits depleted:"):
        return ("X has reached its account-level price limit. Sequitor's own testing cap is disabled; "
                "raise the spend limit in the X Developer Console to run another uncached live search.")
    return message


def read_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def source_metadata(value):
    """Repair API copies only; exact captured text is not evidence about fuller text."""
    excerpts = {(str(row["id"]), row["text"])
                for row in read_json(SNAPSHOT_FILE, {}).get("posts", [])
                if row.get("capture", {}).get("textIsExcerpt") is True}

    def repair(item):
        if isinstance(item, list):
            return [repair(child) for child in item]
        if not isinstance(item, dict):
            return item
        result = {key: repair(child) for key, child in item.items()}
        if isinstance(item.get("text"), str):
            if (str(item.get("id", "")), item["text"]) in excerpts:
                result["textIsExcerpt"] = True
            if item.get("id") == "seed-text":
                result.update(sourceType="input", author="Search input", publishedAt="")
        return result

    return repair(value)


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


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _norm(vector: list[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _space_angle(text: str) -> tuple[float, float]:
    """A deterministic lexical direction when an embedding endpoint is absent.

    Posts sharing distinctive terms receive a related direction. It deliberately
    remains labelled as a lexical fallback in the browser rather than implying a
    semantic embedding that was never served.
    """
    tokens = normalized_words(text)
    if not tokens:
        return 1.0, 0.0
    horizontal = vertical = 0.0
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        angle = int.from_bytes(digest[:8], "big") / 2**64 * math.tau
        horizontal += math.cos(angle)
        vertical += math.sin(angle)
    length = math.hypot(horizontal, vertical)
    return (horizontal / length, vertical / length) if length > 1e-9 else (1.0, 0.0)


def _lexical_space(seed: dict, posts: list[dict]) -> str:
    """Provide a live, clearly marked projection before embeddings are deployed."""
    seed_id = str(seed.get("id") or "")
    for post in posts:
        score = post.get("semanticScore")
        similarity = float(score) if isinstance(score, (int, float)) and math.isfinite(score) else token_overlap(seed.get("text", ""), post.get("text", ""))
        similarity = min(1.0, max(-1.0, similarity))
        if str(post.get("id")) == seed_id:
            similarity, y, z = 1.0, 0.0, 0.0
        else:
            radius = math.sqrt((1.0 - similarity) / 2.0)
            horizontal, vertical = _space_angle(post.get("text", ""))
            y, z = radius * horizontal, radius * vertical
        post["spaceScore"] = round(similarity, 6)
        post["spaceY"] = round(y, 6)
        post["spaceZ"] = round(z, 6)
        post["spaceDirectionQuality"] = 0.0
        post["spaceMethod"] = "lexical direction fallback"
    return "lexical direction fallback"


def add_space_features(seed: dict, posts: list[dict], vectors: list[list[float] | None], source: str = "embeddings") -> str:
    """Attach a seed-relative 2D embedding projection to streamed live posts.

    The radial value remains the exact embedding distance from the seed. The
    angle uses two stable residual basis directions chosen from this run, so it
    is a useful neighbourhood view without claiming clusters or influence.
    """
    if len(vectors) != len(posts) + 1 or not vectors or not vectors[0]:
        return _lexical_space(seed, posts)
    seed_vector = vectors[0]
    if not isinstance(seed_vector, list) or not seed_vector or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in seed_vector):
        return _lexical_space(seed, posts)
    residuals: list[tuple[dict, list[float], float, list[float]]] = []
    for post, vector in zip(posts, vectors[1:]):
        if not isinstance(vector, list) or len(vector) != len(seed_vector) or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
            return _lexical_space(seed, posts)
        similarity = min(1.0, max(-1.0, _dot(seed_vector, vector)))
        residual = [value - similarity * basis for value, basis in zip(vector, seed_vector)]
        residuals.append((post, residual, _norm(residual), similarity))
    ordered = sorted(residuals, key=lambda item: (-item[2], str(item[0].get("id"))))
    if not ordered or ordered[0][2] <= 1e-8:
        return _lexical_space(seed, posts)
    first = [value / ordered[0][2] for value in ordered[0][1]]
    candidates = []
    for post, residual, _, similarity in residuals:
        perpendicular = [value - _dot(residual, first) * basis for value, basis in zip(residual, first)]
        candidates.append((post, residual, similarity, perpendicular, _norm(perpendicular)))
    second = max(candidates, key=lambda item: (item[4], str(item[0].get("id"))))
    if second[4] <= 1e-8:
        return _lexical_space(seed, posts)
    second_basis = [value / second[4] for value in second[3]]
    seed_id = str(seed.get("id") or "")
    for post, residual, residual_norm, similarity in residuals:
        one, two = _dot(residual, first), _dot(residual, second_basis)
        projected_norm = math.hypot(one, two)
        quality = min(1.0, (projected_norm / residual_norm) ** 2) if residual_norm > 1e-8 else 0.0
        if str(post.get("id")) == seed_id:
            similarity, y, z, quality = 1.0, 0.0, 0.0, 0.0
        elif projected_norm > 1e-8:
            radius = math.sqrt((1.0 - similarity) / 2.0)
            y, z = radius * one / projected_norm, radius * two / projected_norm
        else:
            y = z = 0.0
        post["spaceScore"] = round(similarity, 6)
        post["spaceY"] = round(y, 6)
        post["spaceZ"] = round(z, 6)
        post["spaceDirectionQuality"] = round(quality, 6)
        post["spaceMethod"] = f"{source} residual projection"
    return f"{source} residual projection"


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
        "conversationId": str(row.get("conversation_id") or ""),
        "scope": scope, "captureTime": today_utc(), "textIsExcerpt": False,
    }


def post_from_resolved(row, scope: str = "seed") -> dict:
    return {
        "id": row.tweet_id, "text": row.text,
        "publishedAt": row.created_at.isoformat().replace("+00:00", "Z") if row.created_at else "",
        "author": "@" + row.handle, "handle": row.handle,
        "authorId": row.author_id, "likes": row.likes,
        "avatar": row.avatar or None,
        "url": f"https://x.com/{row.handle or 'i'}/status/{row.tweet_id}",
        "scope": scope, "captureTime": today_utc(), "textIsExcerpt": row.text_is_excerpt,
        "quotedPostId": row.quoted_id or None, "parentId": row.parent_id or None,
        "conversationId": row.conversation_id or "",
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


def openai_model() -> str:
    return os.environ.get("SEQUITOR_OPENAI_MODEL", "gpt-4.1")


def recording_for_seed(seed: str) -> dict:
    """Replay a saved conversation when the pasted status has a fixture."""
    match = re.search(r"(?:status|statuses)/(\d+)", seed) or re.fullmatch(r"\s*(\d{15,22})\s*", seed)
    path = ANCHOR_RECORDINGS.get(match.group(1) if match else "")
    if path and path.is_file():
        recorded = read_json(path, {})
        if recorded.get("seedPost"):
            return source_metadata(recorded)
    return recorded_demo()


def recorded_demo() -> dict:
    """Add a separately sourced humor branch without rewriting the old capture."""
    recorded = read_json(CAPTURE_FILE, sample_demo())
    supplement = read_json(DARIO_HUMOR_FILE, {"posts": []})
    posts = supplement.get("posts") or []
    if not posts:
        return source_metadata(recorded)
    saved_periods = recorded.setdefault("savedPeriods", {})
    for post in posts:
        day = post["publishedAt"][:10]
        period = saved_periods.get(day)
        if period:
            period["posts"] = list({row["id"]: row for row in period.get("posts", []) + [post]}.values())
        if day == recorded["selectedDay"]:
            recorded["posts"] = list({row["id"]: row for row in recorded.get("posts", []) + [post]}.values())
    recorded["note"] = (recorded.get("note") or "") + " Three later targeted humor-search posts are included with their own capture timestamps."
    return source_metadata(recorded)


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
        self._openjev_unavailable = False
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

    def fetch_anchor_post(self, tweet_id: str) -> dict | None:
        """Resolve keylessly first, then spend one bounded X lookup if needed."""
        try:
            resolved = resolve(tweet_id)
        except (OSError, ValueError, urllib.error.HTTPError):
            resolved = None
        if resolved and resolved.recoverable_text:
            return post_from_resolved(resolved, "referenced conversation")
        if not self.x:
            return None
        try:
            row = self.x.lookup(tweet_id)
        finally:
            self.save()
        return post_from_x(row, "referenced conversation") if row else None

    def semantic_anchor_candidates(self, entry_post: dict, plan: dict) -> list[dict]:
        """Run one tight, pre-entry search when commentary has no explicit id."""
        queries = list(plan.get("discoveryQueries") or [])
        if not queries:
            entities = [str(item).strip() for item in plan.get("entities") or [] if str(item).strip()]
            if len(entities) >= 2:
                queries = [" ".join(entities[:2])]
        if not self.x or not queries or not entry_post.get("publishedAt"):
            return []
        published = datetime.fromisoformat(entry_post["publishedAt"].replace("Z", "+00:00"))
        end = min(published, now_safe())
        start = end - timedelta(days=28)
        available = MAX_POSTS - self.x.posts_read if MAX_POSTS is not None else 20
        if available < 10:
            return []
        try:
            rows, _ = self.x.search(queries[0] + " -is:retweet", start, end,
                                    max_results=min(20, available))
        finally:
            self.save()
        return [post_from_x(row, "anchor discovery") for row in rows
                if str(row.get("id")) != str(entry_post.get("id"))]

    def select_semantic_anchor(self, entry_post: dict, candidates: list[dict]) -> dict:
        """Let OpenAI select only from supplied ids, then verify the selection."""
        key = os.environ.get("OPENAI_API_KEY")
        if not key or not candidates:
            return entry_post
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "referenced_post_id": {"type": "string"},
                "anchor_rationale": {"type": "string"},
            },
            "required": ["referenced_post_id", "anchor_rationale"],
        }
        evidence = [{"id": post["id"], "text": post.get("text", "")[:500],
                     "author": post.get("handle") or post.get("author"),
                     "publishedAt": post.get("publishedAt")}
                    for post in candidates[:20]]
        body = {
            "model": openai_model(),
            "instructions": (
                "Determine whether the commentary clearly describes one of the candidate public posts as its "
                "referenced announcement or source. Return exactly that candidate's id, or an empty string when "
                "the evidence is ambiguous. Never return an id outside the candidates, infer truth, or treat mere "
                "topic similarity as a reference."
            ),
            "input": json.dumps({"commentary": entry_post.get("text", "")[:1200],
                                 "candidates": evidence}, ensure_ascii=False),
            "text": {"format": {"type": "json_schema", "name": "sequitor_anchor_selection",
                                "strict": True, "schema": schema}},
            "max_output_tokens": 140,
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
            return entry_post
        suggestion = json.loads(content)
        candidate_ids = {str(post["id"]) for post in candidates}
        if str(suggestion.get("referenced_post_id") or "") not in candidate_ids:
            return entry_post
        return choose_semantic_anchor(entry_post, suggestion, self.fetch_anchor_post)

    def count(self, query: str, start: datetime, end: datetime,
              granularity: str = "day") -> list[dict]:
        if not self.x:
            raise RuntimeError("X bearer token unavailable")
        if MAX_COUNTS is not None and self.x.counts_calls >= MAX_COUNTS:
            raise RuntimeError("X counts budget reached for this demo server")
        if granularity not in {"hour", "day"}:
            raise ValueError("Unsupported activity granularity")
        buckets, token = self.x.counts(query, start, end, granularity=granularity)
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
        available = MAX_POSTS - self.x.posts_read if MAX_POSTS is not None else limit
        if MAX_POSTS is not None and available < 10:
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
                "referenced_post_id": {"type": "string"},
                "is_commentary": {"type": "boolean"},
                "anchor_rationale": {"type": "string"},
            },
            "required": ["context_label", "entities", "angles", "uncertainties",
                         "volume_phrase", "discovery_queries", "why_discovery",
                         "referenced_post_id", "is_commentary", "anchor_rationale"],
        }
        body = {
            "model": openai_model(),
            "instructions": (
                "Build an evidence-bounded context card for exploring discussion around an X post. "
                "context_label must be a neutral 3–10 word description, not a truth claim. "
                "entities are only names or organizations grounded in the post. angles are possible "
                "discussion directions, not facts. uncertainties must say what the post alone cannot establish. "
                "volume_phrase must be 2–6 consecutive words copied from the post for a measured histogram. "
                "discovery_queries contains at most two 2–3 word, unquoted search term groups likely to find "
                "the original announcement or source post, not later jokes. Prefer an organization plus a "
                "distinctive event name. If this post is clearly a joke, paraphrase, quote-without-card, or "
                "reaction to a public announcement, set is_commentary true even when the original is unnamed. "
                "In that case discovery_queries may use the well-known public name of the event. Put a status "
                "id in referenced_post_id only when that id appears in the supplied text or URLs; otherwise "
                "use an empty string. Never invent an id. anchor_rationale briefly explains the decision "
                "without claiming the post is true. Do not add X operators, invent quotations, or state that "
                "a rumor is true."
            ),
            "input": text[:3000],
            "text": {"format": {"type": "json_schema", "name": "sequitor_search_plan",
                                "strict": True, "schema": schema}},
            "max_output_tokens": 350,
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
        return {"planVersion": PLAN_VERSION, "contextLabel": str(plan["context_label"])[:110],
                "entities": [str(item)[:50] for item in plan["entities"][:6]],
                "angles": [str(item)[:70] for item in plan["angles"][:4]],
                "uncertainties": [str(item)[:110] for item in plan["uncertainties"][:3]],
                "volumePhrase": primary, "discoveryPhrase": discovery[0] if discovery else None,
                "discoveryQueries": discovery, "expansionQueries": [],
                "whyDiscovery": str(plan["why_discovery"])[:200],
                "referencedPostId": str(plan["referenced_post_id"])[:24],
                "isCommentary": bool(plan["is_commentary"]),
                "anchorRationale": str(plan["anchor_rationale"])[:240],
                "model": data.get("model")}

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
            "model": openai_model(),
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
        """Prefer a Baseten embedding endpoint, then use the OpenAI sponsor path."""
        endpoint = os.environ.get("SEQUITOR_BASETEN_EMBED_URL", "").rstrip("/")
        key = os.environ.get("BASETEN_API_KEY")
        model = os.environ.get("SEQUITOR_BASETEN_EMBED_MODEL", "not-required")
        if not endpoint or not key:
            return self.openai_embed_texts(texts)
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

    def openai_embed_texts(self, texts: list[str]) -> tuple[list[list[float] | None], str]:
        """Small, cached embeddings keep live space coordinates meaningful."""
        key = os.environ.get("OPENAI_API_KEY")
        model = "text-embedding-3-small"
        if not key:
            return [None] * len(texts), "token-overlap fallback"
        cached = self.cache.setdefault("embeddings", {}).setdefault("openai", {}).setdefault(model, {})
        hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        missing = [index for index, digest in enumerate(hashes) if digest not in cached]
        for offset in range(0, len(missing), 64):
            indices = missing[offset:offset + 64]
            body = {"input": [texts[index][:3000] for index in indices], "model": model}
            req = urllib.request.Request("https://api.openai.com/v1/embeddings", data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as response:
                payload = json.load(response)
            rows = sorted(payload.get("data") or [], key=lambda row: int(row.get("index", -1)))
            if len(rows) != len(indices):
                raise RuntimeError("OpenAI embedding response did not match the request")
            for index, row in zip(indices, rows):
                vector = row.get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("OpenAI embedding response was missing a vector")
                cached[hashes[index]] = vector
        self.save()
        return [cached.get(digest) for digest in hashes], f"OpenAI {model}"

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
            reranker_name = "trained reranker"
            if reranker is None:
                reranker = post.get("rerankerScore")
                reranker_name = "Baseten BGE reranker"
            score = (.45 * float(reranker) + .25 * semantic + .18 * lexical + .08 * relation + .04 * scope) if reranker is not None \
                else (.52 * semantic + .25 * lexical + .18 * relation + .05 * scope)
            post["semanticScore"] = round(semantic, 4)
            post["lexicalScore"] = round(lexical, 4)
            post["rankingScore"] = round(score, 4)
            post["rankingMethod"] = "hybrid + " + reranker_name if reranker is not None else "hybrid retrieval"
        space_method = add_space_features(seed, posts, vectors, semantic_method)
        # The resolved seed can live outside a cached period's post list. It is
        # still the reference point for the live scene, so keep it centered.
        seed["spaceScore"] = 1.0
        seed["spaceY"] = 0.0
        seed["spaceZ"] = 0.0
        seed["spaceDirectionQuality"] = 0.0
        seed["spaceMethod"] = space_method
        return {"status": "ready", "semantic": semantic_method,
                "reranker": "connected" if any(post.get("sameClaimScore") is not None or post.get("rerankerScore") is not None for post in posts) else "awaiting trained endpoint",
                "space": space_method,
                **({"embeddingError": embedding_error} if embedding_error else {})}

    def classify(self, seed_text: str, posts: list[dict], emit=None) -> dict:
        key = os.environ.get("BASETEN_API_KEY")
        if not key or not posts:
            return {"status": "unavailable", "model": None}
        openjev_url = os.environ.get("SEQUITOR_JEV_RERANK_URL", "").strip()
        if openjev_url and not self._openjev_unavailable:
            try:
                # OpenJev supplies the claim score used by the hybrid ranker.
                # The Chain still adds response categories and observed edges.
                jev = OpenJevReranker(key, openjev_url).score(seed_text, posts, emit=emit)
            except Exception as exc:
                self._openjev_unavailable = True
                if emit:
                    emit("stage", {"name": "OpenJev unavailable; continuing with Baseten Chain",
                                   "reason": type(exc).__name__})
            else:
                chain_url = os.environ.get("SEQUITOR_BASETEN_CHAIN_URL", "").strip()
                if not chain_url:
                    return jev
                # Keep Jev scores even when the Chain's baseline reranker arrives.
                # rank_posts prioritizes sameClaimScore over rerankerScore.
                try:
                    chain = BasetenChainClient(key, chain_url).classify(seed_text, posts, emit=emit)
                    return {**chain, "openjev": jev}
                except Exception as exc:
                    if emit:
                        emit("stage", {"name": "Baseten Chain unavailable; retaining OpenJev ranking",
                                       "reason": type(exc).__name__})
                    return jev
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
        if emit:
            send_event = emit
            emit = lambda kind, payload: send_event(kind, source_metadata(payload))
        run = self.cache["runs"].get(run_id)
        if not run:
            raise ValueError("Run not found")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid UTC day")
        key = run_id + ":" + day
        if key in self.cache["periods"] and self.cache["periods"][key].get("schemaVersion") == 5 and self.cache["periods"][key].get("discoveryQuery") == run["searchPlan"].get("discoveryPhrase"):
            cached_period = self.cache["periods"][key]
            if emit:
                emit("stage", {"name": "Loading cached posts", "source": "cache"})
                ordered = sorted(cached_period["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_post_batches(emit, ordered, size=16, pause=0.035)
            cached_model = cached_period.get("model", {})
            status = cached_model.get("status") if isinstance(cached_model, dict) else None
            embedded_openjev = cached_model.get("openjev") if isinstance(cached_model, dict) else None
            has_openjev = status == "openjev" or (isinstance(embedded_openjev, dict)
                                                   and embedded_openjev.get("status") == "openjev")
            wants_openjev = bool(os.environ.get("SEQUITOR_JEV_RERANK_URL")) and not has_openjev
            refreshed_model = False
            if status == "unavailable" or wants_openjev or (os.environ.get("SEQUITOR_BASETEN_CHAIN_URL") and status != "baseten chain"):
                cached_period["model"] = self.classify(run["seedPost"]["text"], cached_period["posts"], emit=emit)
                run["posts"] = cached_period["posts"]
                run["model"] = {"openai": run["searchPlan"].get("model"), "baseten": cached_period["model"]}
                refreshed_model = True
                self.save()
                if run.get("seed") == DEFAULT_SEED:
                    write_json(CAPTURE_FILE, run)
            needs_openjev_rank = any(str(post.get("rerankerModel") or "").startswith("OpenJev")
                                     and "OpenJev" not in str(post.get("rankingMethod") or "")
                                     for post in cached_period["posts"])
            if refreshed_model or needs_openjev_rank or any("rankingScore" not in post or "spaceY" not in post or "spaceZ" not in post for post in cached_period["posts"]):
                retrieval = self.rank_posts(run["seedPost"], cached_period["posts"])
                cached_period["model"] = {**cached_period.get("model", {}), "retrieval": retrieval}
                if emit:
                    emit_post_batches(emit, cached_period["posts"], size=16, pause=0.035)
                self.save()
            current_spend = round(self.x.spend, 3) if self.x else 0
            cached_period["xSpend"] = current_spend
            run["xSpend"] = current_spend
            run.setdefault("savedPeriods", {})[day] = cached_period
            self.save()
            if run.get("seed") == DEFAULT_SEED:
                write_json(CAPTURE_FILE, run)
            return source_metadata(cached_period)
        prior = self.cache["periods"].get(key)
        if prior:
            primary = [p for p in prior["posts"] if p.get("scope") == "measured phrase"]
            partial = prior.get("partial", False)
        else:
            if emit:
                emit("stage", {"name": "Retrieving phrase matches"})
            primary, partial = self.search(run["query"], day,
                                           limit=100 if day == run["selectedDay"] else 70)
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
                rows, partial_result = self.search(query, day, limit=60, scope="broader discovery")
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
                                                         limit=100, scope="direct conversation")
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
        entry_post = run.get("entryPost")
        if entry_post and str(entry_post.get("id")) != seed_id:
            unique.setdefault(str(entry_post["id"]), entry_post)
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
                    rows, partial_result = self.search(query, day, limit=50, scope="context expansion")
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
        result = {"schemaVersion": 5, "discoveryQuery": run["searchPlan"].get("discoveryPhrase"),
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
        return source_metadata(result)

    def activity(self, run_id: str, day: str, granularity: str) -> dict:
        """Fetch and cache an hourly count series for a selected UTC day."""
        run = self.cache["runs"].get(run_id)
        if not run:
            raise ValueError("Run not found")
        if granularity != "hour":
            raise ValueError("Only hourly activity is fetched on demand")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid UTC day")
        key = f"activity:{day}:{granularity}"
        cached = run.setdefault("activity", {}).get(key)
        if cached:
            return cached
        start, end = day_bounds(day)
        rows = self.count(run["query"], start, end, granularity="hour")
        buckets = sorted([{"day": row["start"],
                           "count": int(row.get("tweet_count", row.get("post_count", 0))),
                           "coverage": "partial" if row.get("sequitor_partial") else "complete"}
                          for row in rows], key=lambda row: row["day"])
        result = {"granularity": "hour", "day": day, "query": run["query"], "buckets": buckets,
                  "xSpend": round(self.x.spend, 3) if self.x else 0}
        run["activity"][key] = result
        run["xSpend"] = result["xSpend"]
        self.save()
        return result

    def resolve_conversation_seed(self, seed: str, emit=None) -> dict:
        """Identify the conversation origin before any volume search."""
        original_text = seed
        entry_post = None
        seed_post = None
        anchor_method = "self"
        anchor_hops = 0
        match = re.search(r"/(?:status|statuses)/(\d+)", seed)
        if match:
            if emit:
                emit("stage", {"name": "Resolving the starting post"})
            entry_post = self.fetch_anchor_post(match.group(1))
            if not entry_post:
                raise RuntimeError("The seed post's text is unavailable; paste its text instead")
            original_text = entry_post["text"]
            walked = conversation_anchor(entry_post, self.fetch_anchor_post)
            seed_post = walked["anchor"]
            anchor_method = walked["method"]
            anchor_hops = walked["hops"]
            if seed_post["id"] != entry_post["id"]:
                entry_post["scope"] = "entry commentary"
                seed_post["scope"] = "seed"

        plan = None
        plan_error = None
        commentary_plan = None
        plan_attempted = False
        if entry_post and seed_post["id"] == entry_post["id"]:
            try:
                plan_attempted = True
                commentary_plan = self.openai_plan(entry_post["text"])
                plan = commentary_plan
            except Exception as exc:
                plan_error = exc
            if commentary_plan:
                semantic = entry_post
                if commentary_plan.get("referencedPostId"):
                    semantic = choose_semantic_anchor(
                        entry_post,
                        {"referenced_post_id": commentary_plan["referencedPostId"]},
                        self.fetch_anchor_post,
                    )
                if semantic["id"] == entry_post["id"] and commentary_plan.get("isCommentary"):
                    try:
                        candidates = self.semantic_anchor_candidates(entry_post, commentary_plan)
                        semantic = self.select_semantic_anchor(entry_post, candidates)
                    except Exception as exc:
                        commentary_plan["anchorSearchError"] = type(exc).__name__
                if semantic["id"] != entry_post["id"]:
                    entry_post["scope"] = "entry commentary"
                    semantic["scope"] = "seed"
                    seed_post = semantic
                    anchor_method = "semantic"
                    anchor_hops = 1
                    try:
                        plan_attempted = True
                        plan = self.openai_plan(seed_post["text"])
                        plan["referencedPostId"] = semantic["id"]
                        plan["isCommentary"] = commentary_plan["isCommentary"]
                        plan["anchorRationale"] = commentary_plan["anchorRationale"]
                    except Exception as exc:
                        plan = None
                        plan_error = exc
        if plan is None and not plan_attempted:
            try:
                plan_attempted = True
                plan = self.openai_plan(seed_post["text"] if seed_post else original_text)
            except Exception as exc:
                plan_error = exc
        planning_text = seed_post["text"] if seed_post else original_text
        if plan is None:
            words = re.findall(r"[\w'-]+", planning_text)
            plan = {"planVersion": PLAN_VERSION, "contextLabel": "Unstructured seed post",
                    "entities": [], "angles": [], "uncertainties": ["Context planning was unavailable."],
                    "volumePhrase": phrase(" ".join(words[:4])), "discoveryPhrase": None,
                    "discoveryQueries": [], "expansionQueries": [], "whyDiscovery": "",
                    "referencedPostId": (commentary_plan or {}).get("referencedPostId", ""),
                    "isCommentary": bool((commentary_plan or {}).get("isCommentary")),
                    "anchorRationale": (commentary_plan or {}).get("anchorRationale", ""),
                    "model": None, "error": type(plan_error).__name__ if plan_error else "Unavailable"}
        return {
            "original_text": original_text, "entry_post": entry_post, "seed_post": seed_post,
            "anchor_method": anchor_method, "anchor_hops": anchor_hops, "plan": plan,
            "planning_text": planning_text,
        }

    def explore(self, seed: str, emit=None) -> dict:
        if emit:
            send_event = emit
            emit = lambda kind, payload: send_event(kind, source_metadata(payload))
        seed = seed.strip()[:2000]
        if not seed:
            seed = DEFAULT_SEED
        cache_key = re.sub(r"[^a-z0-9]+", "-", seed.lower())[:100]
        stale = self.cache["runs"].get(cache_key)
        if stale and stale.get("anchorVersion") != ANCHOR_VERSION:
            self.cache["runs"].pop(cache_key, None)
            for period_key in [key for key in self.cache["periods"] if key.startswith(cache_key + ":")]:
                self.cache["periods"].pop(period_key, None)
            self.save()
        if cache_key in self.cache["runs"]:
            cached = self.cache["runs"][cache_key]
            if cached.get("searchPlan", {}).get("planVersion") != PLAN_VERSION:
                try:
                    revised = self.openai_plan(cached["seedPost"]["text"])
                    cached["searchPlan"] = revised
                    self.save()
                    self.period(cache_key, cached["selectedDay"])
                except Exception as exc:
                    cached["searchPlan"]["revisionError"] = type(exc).__name__
                    self.save()
            needs_space = ("spaceY" not in cached.get("seedPost", {}) or "spaceZ" not in cached.get("seedPost", {})
                           or any("spaceY" not in post or "spaceZ" not in post for post in cached.get("posts", [])))
            needs_semantic_upgrade = bool(os.environ.get("OPENAI_API_KEY")) and any(
                post.get("spaceMethod") == "lexical direction fallback" for post in cached.get("posts", []))
            needs_openjev_rank = any(str(post.get("rerankerModel") or "").startswith("OpenJev")
                                     and "OpenJev" not in str(post.get("rankingMethod") or "")
                                     for post in cached.get("posts", []))
            if needs_space or needs_semantic_upgrade or needs_openjev_rank:
                retrieval = self.rank_posts(cached["seedPost"], cached["posts"])
                cached["model"] = {**cached.get("model", {}), "retrieval": retrieval}
                self.save()
            if emit:
                seed_payload = {"post": cached["seedPost"],
                                "text": cached["seedPost"].get("text", "")[:2000]}
                if cached.get("entryPost") and cached["entryPost"].get("id") != cached["seedPost"].get("id"):
                    seed_payload["entryPost"] = cached["entryPost"]
                emit("seed.resolved", seed_payload)
                emit_activity(emit, cached, "cache")
                ordered = sorted(cached["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_progressive_posts(emit, ordered)
            current_model = cached.get("model", {}).get("baseten")
            current_status = current_model.get("status") if isinstance(current_model, dict) else current_model
            embedded_openjev = current_model.get("openjev") if isinstance(current_model, dict) else None
            has_openjev = current_status == "openjev" or (isinstance(embedded_openjev, dict)
                                                            and embedded_openjev.get("status") == "openjev")
            wants_openjev = bool(os.environ.get("SEQUITOR_JEV_RERANK_URL")) and not has_openjev
            if wants_openjev or (os.environ.get("SEQUITOR_BASETEN_CHAIN_URL") and current_status != "baseten chain"):
                model = self.classify(cached["seedPost"]["text"], cached["posts"], emit=emit)
                cached["model"] = {**cached.get("model", {}), "baseten": model}
                retrieval = self.rank_posts(cached["seedPost"], cached["posts"])
                cached["model"] = {**cached.get("model", {}), "retrieval": retrieval}
                if emit:
                    emit_post_batches(emit, cached["posts"], size=16, pause=0.035)
                self.save()
            return source_metadata(cached)
        if not self.x:
            raise RuntimeError("X bearer token unavailable")
        resolved = self.resolve_conversation_seed(seed, emit=emit)
        original_text = resolved["original_text"]
        entry_post = resolved["entry_post"]
        seed_post = resolved["seed_post"]
        anchor_method = resolved["anchor_method"]
        anchor_hops = resolved["anchor_hops"]
        plan = resolved["plan"]
        planning_text = resolved["planning_text"]
        if emit:
            seed_payload = {"post": seed_post, "text": planning_text[:2000],
                            "anchorMethod": anchor_method, "anchorHops": anchor_hops}
            if entry_post and seed_post and entry_post["id"] != seed_post["id"]:
                seed_payload["entryPost"] = entry_post
            emit("seed.resolved", seed_payload)
            emit("stage", {"name": "Planning bounded discovery with OpenAI"})
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
        seed_day = seed_post["publishedAt"][:10] if seed_post else ""
        seed_bucket = next((bucket for bucket in buckets if bucket["day"] == seed_day), None)
        selected = seed_day if seed_bucket and seed_bucket["count"] else peak["day"]
        run = {"id": cache_key, "seed": seed, "title": planning_text.split("\n")[0][:110],
               "kind": "live", "capturedAt": today_utc(),
               "anchorVersion": ANCHOR_VERSION, "anchorMethod": anchor_method,
               "anchorHops": anchor_hops,
               "scope": "X counts for one context query" if plan.get("volumeFallback") else "X counts for one exact phrase",
               "query": chart_query, "buckets": buckets, "posts": [],
               "selectedDay": selected, "rankingCoverage": "not collected yet",
               "searchPlan": plan, "seedPost": seed_post or {"id": "seed-text", "text": original_text,
                                                  "sourceType": "input", "publishedAt": "", "author": "Search input"},
               "model": {"openai": plan.get("model"), "baseten": "pending"},
               "note": (f"The exact phrase {measured_phrase} had no matches. Bars measure the grounded context query {chart_query}. "
                        "The feed includes separately marked discovery branches." if plan.get("volumeFallback") else
                        "Bars measure the exact phrase only. The feed can include separately marked discovery branches."),
               "xSpend": round(self.x.spend, 3)}
        if entry_post and seed_post and entry_post["id"] != seed_post["id"]:
            run["entryPost"] = entry_post
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
        return source_metadata(run)


APP = Sequitor()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, obj: dict) -> None:
        body = json.dumps(source_metadata(obj), ensure_ascii=False).encode()
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
                    body = json.dumps(source_metadata(event), ensure_ascii=False, separators=(",", ":"))
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
                                 "scope": "referenced post", "captureTime": today_utc(),
                                 "textIsExcerpt": found.text_is_excerpt})
                return
            if url.path == "/api/period" and method == "GET":
                qs = parse_qs(url.query)
                with APP.lock:
                    self._send(200, APP.period(qs.get("run", [""])[0], qs.get("day", [""])[0]))
                return
            if url.path == "/api/activity" and method == "GET":
                qs = parse_qs(url.query)
                with APP.lock:
                    self._send(200, APP.activity(qs.get("run", [""])[0], qs.get("day", [""])[0],
                                                  qs.get("granularity", [""])[0]))
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
    if os.environ.get("RAILWAY_ENVIRONMENT_ID") and not os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        raise RuntimeError("Attach a Railway volume before enabling paid live searches")
    port = int(os.environ.get("PORT") or os.environ.get("SEQUITOR_PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    post_cap = MAX_POSTS if MAX_POSTS is not None else "unlimited"
    counts_cap = MAX_COUNTS if MAX_COUNTS is not None else "unlimited"
    print(f"Sequitor at http://{host}:{port} (X cap: {post_cap} posts, {counts_cap} counts calls)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
