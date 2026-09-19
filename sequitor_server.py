"""Small, bounded demo API for Sequitor. Run with `python3 sequitor_server.py`.

Only the server reads provider keys. Search results and spend counters are cached in
work/sequitor-cache.json, which is deliberately excluded from Git.
"""
from __future__ import annotations

import json
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

ROOT = Path(__file__).resolve().parent
CACHE_FILE = ROOT / "work" / "sequitor-cache.json"
CAPTURE_FILE = ROOT / "demo" / "recordings" / "sequitor-live.json"
SNAPSHOT_FILE = ROOT / "demo" / "recordings" / "pace-the-frontier" / "snapshot.json"
EVENT_DIR = ROOT / "work" / "sequitor-streams"
DEFAULT_SEED = "https://x.com/DarioAmodei/status/2098773920774074715"
MAX_POSTS = 600  # Approximately $3.00 in X post charges, below the $10 test credit.
MAX_COUNTS = 20  # Approximately $0.20 more at the repository's measured price.


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
                    recorded = read_json(CAPTURE_FILE, sample_demo())
                    job.emit("run.ready", {**recorded, "kind": "saved", "posts": [],
                                           "savedPeriods": {}, "streamSource": "recorded"})
                    posts = sorted(recorded.get("posts", []),
                                   key=lambda post: -(post.get("likes") or 0))
                    for index in range(0, len(posts), 12):
                        job.emit("posts.upsert", {"posts": posts[index:index + 12]})
                        time.sleep(0.045)
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


def emit_post_batches(emit, posts: list[dict], size: int = 10, pause: float = 0.025) -> None:
    """Pace a returned X page briefly so the browser can paint between updates."""
    if not emit:
        return
    for index in range(0, len(posts), size):
        emit("posts.upsert", {"posts": posts[index:index + size]})
        if index + size < len(posts):
            time.sleep(pause)


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


class Sequitor:
    def __init__(self) -> None:
        load_local_env()
        self.lock = threading.Lock()
        self.cache = read_json(CACHE_FILE, {"runs": {}, "periods": {}, "ledger": {}})
        self.cache.setdefault("runs", {})
        self.cache.setdefault("periods", {})
        self.cache.setdefault("ledger", {})
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
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OpenAI API key unavailable")
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "volume_phrase": {"type": "string"},
                "discovery_query": {"type": "string"},
                "why_discovery": {"type": "string"},
            },
            "required": ["volume_phrase", "discovery_query", "why_discovery"],
        }
        body = {
            "model": "gpt-4.1-mini",
            "instructions": (
                "Plan X archive discovery around this post. volume_phrase must be 2–6 "
                "consecutive words copied from the post, for a measured histogram. "
                "discovery_query must be 2–3 separate, unquoted search terms likely to "
                "occur in posts about this event that do NOT repeat the volume_phrase. "
                "Prefer a name plus distinctive concept, e.g. 'Dario slowdown'. "
                "Do not invent a quotation, add operators, or write a sentence."
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
        secondary = terms(plan["discovery_query"])
        return {"volumePhrase": primary, "discoveryPhrase": secondary,
                "whyDiscovery": plan["why_discovery"][:200], "model": data.get("model")}

    def classify(self, seed_text: str, posts: list[dict]) -> dict:
        key = os.environ.get("BASETEN_API_KEY")
        if not key or not posts:
            return {"status": "unavailable", "model": None}
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
        if key in self.cache["periods"] and self.cache["periods"][key].get("schemaVersion") == 3 and self.cache["periods"][key].get("discoveryQuery") == run["searchPlan"].get("discoveryPhrase"):
            cached_period = self.cache["periods"][key]
            if emit:
                emit("stage", {"name": "Loading cached posts", "source": "cache"})
                ordered = sorted(cached_period["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_post_batches(emit, ordered, size=16, pause=0.035)
            if cached_period.get("model", {}).get("status") == "unavailable":
                cached_period["model"] = self.classify(run["seedPost"]["text"], cached_period["posts"])
                run["posts"] = cached_period["posts"]
                run["model"] = {"openai": run["searchPlan"].get("model"), "baseten": cached_period["model"]}
                self.save()
                if run.get("seed") == DEFAULT_SEED:
                    write_json(CAPTURE_FILE, run)
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
            emit_post_batches(emit, sorted(primary, key=lambda post: -(post.get("likes") or 0)))
        # One bounded secondary search creates a real branch outside the chart's
        # literal phrase scope. It is explicitly labelled as broader discovery.
        secondary, extra_partial = [], False
        if day == run["selectedDay"] and run["searchPlan"].get("discoveryPhrase") and run["searchPlan"].get("discoveryPhrase") != run["query"]:
            if emit:
                emit("stage", {"name": "Looking beyond the exact phrase"})
            secondary, extra_partial = self.search(run["searchPlan"]["discoveryPhrase"],
                                                   day, limit=40, scope="broader discovery")
            if emit and secondary:
                emit_post_batches(emit, secondary)
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
        if emit:
            emit_post_batches(emit, posts, size=24, pause=0)
            emit("stage", {"name": "Curating retrieved posts with Baseten"})
        model = self.classify(run["seedPost"]["text"], posts)
        if emit:
            updates = [post for post in posts if post.get("basetenPick") or post.get("sameClaimScore") is not None]
            emit_post_batches(emit, updates, size=12, pause=0)
            emit("model.ready", {"model": model})
        result = {"schemaVersion": 3, "discoveryQuery": run["searchPlan"].get("discoveryPhrase"),
                  "day": day, "posts": posts,
                  "rankingCoverage": "top retrieved posts; search may be truncated" if partial or extra_partial
                  else "top retrieved posts; phrase scope plus one related search",
                  "partial": partial or extra_partial, "model": model,
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
            if cached.get("searchPlan", {}).get("planVersion") != 3:
                try:
                    revised = self.openai_plan(cached["seedPost"]["text"])
                    revised["planVersion"] = 3
                    cached["searchPlan"] = revised
                    self.save()
                    self.period(cache_key, cached["selectedDay"])
                except Exception as exc:
                    cached["searchPlan"]["revisionError"] = type(exc).__name__
                    self.save()
            if emit:
                emit("run.ready", {**cached, "posts": [], "savedPeriods": {},
                                   "streamSource": "cache"})
                ordered = sorted(cached["posts"], key=lambda post: -(post.get("likes") or 0))
                emit_post_batches(emit, ordered, size=16, pause=0.035)
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
                         "url": f"https://x.com/{original.handle}/status/{original.tweet_id}",
                         "scope": "seed", "captureTime": today_utc(), "textIsExcerpt": False,
                         "quotedPostId": None, "parentId": None}
        if emit:
            emit("seed.resolved", {"post": seed_post, "text": original_text[:2000]})
            emit("stage", {"name": "Planning bounded discovery with OpenAI"})
        try:
            plan = self.openai_plan(original_text)
            plan["planVersion"] = 3
        except Exception as exc:
            # An OpenAI failure is visible in provenance, never silently counted as API use.
            words = re.findall(r"[\w'-]+", original_text)
            plan = {"volumePhrase": phrase(" ".join(words[:4])),
                    "discoveryPhrase": None, "whyDiscovery": "",
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
        if not buckets:
            raise RuntimeError("No X activity found for the measured phrase")
        peak = max(buckets, key=lambda row: row["count"])
        selected = seed_post["publishedAt"][:10] if seed_post else peak["day"]
        run = {"id": cache_key, "seed": seed, "title": original_text.split("\n")[0][:110],
               "kind": "live", "capturedAt": today_utc(), "scope": "X counts for one exact phrase",
               "query": plan["volumePhrase"], "buckets": buckets, "posts": [],
               "selectedDay": selected, "rankingCoverage": "not collected yet",
               "searchPlan": plan, "seedPost": seed_post or {"id": "seed-text", "text": original_text,
                                                  "publishedAt": selected + "T00:00:00Z", "author": "Seed text"},
               "model": {"openai": plan.get("model"), "baseten": "pending"},
               "note": "Bars measure the exact phrase only. The feed can include a separately marked related search.",
               "xSpend": round(self.x.spend, 3)}
        self.cache["runs"][cache_key] = run
        self.save()
        if emit:
            emit("run.ready", {**run, "streamSource": "live"})
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
                recorded = read_json(CAPTURE_FILE, sample_demo())
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
    port = int(os.environ.get("SEQUITOR_PORT", "8765"))
    print(f"Sequitor at http://127.0.0.1:{port} (X cap: {MAX_POSTS} posts, {MAX_COUNTS} counts calls)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
