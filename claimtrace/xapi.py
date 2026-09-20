"""X API client with a rate-limit governor, spend guard, and the bisect.

Design notes earned the hard way:
  * Billing is per ROW RETURNED. A probe that matches nothing is FREE, which is
    what makes existence-bisection cheap near an origin.
  * counts/all is FLAT rate per request regardless of volume, so it is the right
    tool for anything volumetric and for density checks.
  * search/all returns NEWEST-FIRST and truncates hard. A dense window can never
    be read directly; you must keep bisecting.
  * Never paginate an unbounded window. That mistake cost $8.50 in one run.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config as C


class BudgetExceeded(RuntimeError):
    pass


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# X query syntax is narrow. An LLM will happily emit prose with commas and
# parenthetical asides, which returns HTTP 400 "no viable alternative at
# character ','". Everything model-generated must pass through here.
_ALLOWED = re.compile(r'[^A-Za-z0-9_\'"#@:\- ]')


def sanitize_query(raw: str, max_words: int = 12) -> str:
    """Coerce free text into something the search grammar accepts.

    The failure modes here are all real, observed from model output:
      * prose with commas       -> "no viable alternative at character ','"
      * pre-quoted negatives    -> "Phrases cannot be empty"
      * an explicit `AND` token -> X uses IMPLICIT and; a space already means AND,
                                   and the literal word is not an operator. `OR` IS.
    """
    if not raw:
        return ""
    s = re.sub(r"\([^)]*\)", " ", raw)                 # drop parenthetical asides
    s = re.sub(r"\s+(AND|&&|\+)\s+", " ", s, flags=re.I)   # implicit AND only
    s = _ALLOWED.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.count('"') % 2:                               # unbalanced quote breaks it
        s = s.replace('"', "")
    s = re.sub(r"(^|\s)[-:#@]+(\s|$)", " ", s)         # stray operator chars
    words = s.split()
    if len(words) > max_words:
        # Truncating mid-phrase would unbalance quotes, so cut on a safe boundary.
        s = " ".join(words[:max_words])
        if s.count('"') % 2:
            s = s.rsplit('"', 1)[0]
    s = re.sub(r"\s+", " ", s).strip()
    # A query of nothing but operators is not a query.
    return "" if s.upper() in {"OR", ""} else s


def is_handle(raw: str) -> bool:
    """`from:` needs an actual screen name, not a description."""
    if not raw:
        return False
    h = raw.lstrip("@").strip()
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,15}", h))


def now_safe() -> datetime:
    """end_time cannot be the present moment; the API returns 400."""
    return datetime.now(timezone.utc) - timedelta(minutes=C.END_TIME_SLACK_MINUTES)


# Snowflake IDs carry their own creation time. This is FREE: no API call, no cost,
# and it works on DELETED tweets, which is exactly the case we care about.
ARCHIVE_FLOOR_TS = C.ARCHIVE_FLOOR.timestamp()   # for axis maths

SNOWFLAKE_EPOCH_MS = 1288834974657
SNOWFLAKE_MIN_ID = 29700859904        # ids below this predate Snowflake (pre-Nov 2010)


def id_to_time(tweet_id) -> datetime:
    """Decode a Snowflake tweet id to its UTC creation time.

    Verified: id 869766994899468288 -> 2017-05-31T04:06:25Z, which is the deleted
    covfefe original. Our bisect found the earliest *surviving* post at 04:06:26Z,
    so the true gap was one second.
    """
    i = int(tweet_id)
    if i < SNOWFLAKE_MIN_ID:
        raise ValueError(f"id {i} predates Snowflake; no embedded timestamp")
    return datetime.fromtimestamp(((i >> 22) + SNOWFLAKE_EPOCH_MS) / 1000, tz=timezone.utc)


def id_is_plausible_for(tweet_id, when: datetime, tolerance_s: int = 5) -> bool:
    """Sanity-check an id against a claimed date. Fabricated ids fail this."""
    try:
        return abs((id_to_time(tweet_id) - when).total_seconds()) <= tolerance_s
    except ValueError:
        return True      # pre-Snowflake ids cannot be checked, so do not fail them


class XClient:
    def __init__(self, bearer: str, post_budget: Optional[int] = C.DEFAULT_POST_BUDGET, verbose: bool = False):
        if not bearer:
            raise ValueError("X_BEARER is empty")
        self._bearer = bearer
        self.post_budget = post_budget
        self.verbose = verbose
        self.posts_read = 0
        self.counts_calls = 0
        self.search_calls = 0
        self._window = deque()      # timestamps of recent requests
        self._last_call = 0.0

    # ------------------------------------------------------------- accounting
    @property
    def spend(self) -> float:
        return self.posts_read * C.COST_PER_POST_READ + self.counts_calls * C.COST_PER_COUNTS_ALL

    def _guard(self, about_to_bill: int) -> None:
        if self.post_budget is not None and self.posts_read + about_to_bill > self.post_budget:
            raise BudgetExceeded(
                f"would exceed post budget: {self.posts_read}+{about_to_bill} > {self.post_budget}"
            )

    def _throttle(self) -> None:
        """Respect both the 1/sec and the 300/15min limits."""
        gap = time.time() - self._last_call
        if gap < C.X_MIN_REQUEST_INTERVAL:
            time.sleep(C.X_MIN_REQUEST_INTERVAL - gap)
        cutoff = time.time() - C.X_RATE_WINDOW_SECONDS
        while self._window and self._window[0] < cutoff:
            self._window.popleft()
        if len(self._window) >= C.X_RATE_WINDOW_REQUESTS:
            sleep_for = self._window[0] + C.X_RATE_WINDOW_SECONDS - time.time() + 1
            if self.verbose:
                print(f"   [rate] window full, sleeping {sleep_for:.0f}s")
            time.sleep(max(sleep_for, 1))

    # ----------------------------------------------------------------- request
    def _get(self, path: str, params: dict) -> dict:
        self._throttle()
        url = f"{C.X_API}/{path}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._bearer}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req) as resp:
                    body = json.loads(resp.read())
                self._last_call = time.time()
                self._window.append(self._last_call)
                return body
            except urllib.error.HTTPError as e:
                text = e.read().decode()[:250]
                if e.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                if e.code == 402:
                    raise BudgetExceeded(f"X credits depleted: {text}") from None
                raise RuntimeError(f"X HTTP {e.code}: {text}") from None
        raise RuntimeError("X API: retries exhausted on 429")

    # ------------------------------------------------------------------ counts
    def counts(self, query: str, start: datetime, end: datetime, token: str = None,
               granularity: str = "day"):
        """One page = 31 days, newest first. FLAT rate, no post billing."""
        params = {"query": query, "start_time": iso(start), "end_time": iso(end),
                  "granularity": granularity}
        if token:
            params["next_token"] = token
        d = self._get("tweets/counts/all", params)
        self.counts_calls += 1
        meta = d.get("meta", {})
        return d.get("data", []), meta.get("next_token")

    def counts_total(self, query: str, start: datetime, end: datetime, max_pages: int = 40) -> int:
        """Sum every bucket across a window. NOTE: meta.total_tweet_count is
        per-page only (measured), so it cannot be used to shortcut this."""
        total, token, pages = 0, None, 0
        while pages < max_pages:
            buckets, token = self.counts(query, start, end, token)
            total += sum(b.get("tweet_count", b.get("post_count", 0)) for b in buckets)
            pages += 1
            if not token:
                break
        return total

    def daily_curve(self, query: str, days: int = 30):
        """One call covers 31 days. Returns [(date, count)] oldest first."""
        end = now_safe()
        buckets, _ = self.counts(query, end - timedelta(days=days), end)
        rows = [(b["start"][:10], b.get("tweet_count", b.get("post_count", 0))) for b in buckets]
        return sorted(rows)

    # ------------------------------------------------------------------ search
    def search(self, query: str, start: datetime, end: datetime,
               max_results: int = C.SEARCH_MIN_RESULTS, token: str = None):
        mr = max(C.SEARCH_MIN_RESULTS, min(max_results, C.SEARCH_MAX_RESULTS))
        self._guard(mr)
        params = {"query": query, "start_time": iso(start), "end_time": iso(end),
                  "max_results": mr,
                  "tweet.fields": "created_at,public_metrics,author_id,lang,referenced_tweets,conversation_id",
                  "expansions": "author_id",
                  "user.fields": "name,username,profile_image_url"}
        if token:
            params["next_token"] = token
        d = self._get("tweets/search/all", params)
        rows = d.get("data", [])
        users = {str(user.get("id")): user for user in d.get("includes", {}).get("users", [])}
        for row in rows:
            user = users.get(str(row.get("author_id")))
            if user:
                row["sequitor_author"] = user
        self.posts_read += len(rows)
        self.search_calls += 1
        return rows, d.get("meta", {}).get("next_token")

    def lookup(self, tweet_id: str):
        """Read one post and its references, charging every returned post."""
        # The target is always one billed read; returned reference expansions are
        # added to the same ledger below.
        self._guard(1)
        params = {
            "tweet.fields": "created_at,public_metrics,author_id,lang,referenced_tweets,conversation_id",
            "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id",
            "user.fields": "name,username,profile_image_url",
        }
        d = self._get(f"tweets/{tweet_id}", params)
        row = d.get("data")
        included = d.get("includes", {})
        users = {str(user.get("id")): user for user in included.get("users", [])}
        if row:
            user = users.get(str(row.get("author_id")))
            if user:
                row["sequitor_author"] = user
        billed_ids = ({str(row["id"])} if row and row.get("id") else set())
        billed_ids.update(str(item["id"]) for item in included.get("tweets", []) if item.get("id"))
        self.posts_read += len(billed_ids)
        return row

    def exists_before(self, query: str, when: datetime) -> bool:
        """One request. FREE when it misses, because 0 rows returned = 0 billed."""
        rows, _ = self.search(query, C.ARCHIVE_FLOOR, when)
        return bool(rows)

    # ------------------------------------------------------------------ bisect
    def earliest(self, query: str, emit=None):
        """Find the earliest matching post.

        Phase 1 bisects to the hour, phase 2 to two seconds. Never paginates a
        dense window, which is the whole point: for anything viral, the earliest
        instance sits inside the explosion and the final window is huge.

        `emit` is an Emitter. Each probe fires an event, which is what makes the
        ~60 second search watchable instead of a dead wait.
        """
        end = now_safe()
        if not self.exists_before(query, end):
            return None, {"probes": 1, "found": False}

        lo, hi, probes = C.ARCHIVE_FLOOR, end, 1
        if emit:
            emit.probe(1, "coarse", lo.timestamp(), hi.timestamp(), True,
                       (hi - lo).total_seconds())

        for phase, floor in (("coarse", timedelta(hours=1)), ("fine", timedelta(seconds=2))):
            while (hi - lo) > floor:
                mid = lo + (hi - lo) / 2
                hit = self.exists_before(query, mid)
                probes += 1
                lo, hi = (lo, mid) if hit else (mid, hi)
                if emit:
                    emit.probe(probes, phase, lo.timestamp(), hi.timestamp(), hit,
                               (hi - lo).total_seconds())

        rows, _ = self.search(query, lo - timedelta(seconds=30), hi + timedelta(seconds=5))
        rows.sort(key=lambda r: r["created_at"])
        return (rows[0] if rows else None), {"probes": probes, "found": bool(rows),
                                            "window_start": iso(lo)}

    # ----------------------------------------------------------------- cascade
    def cascade(self, query: str, min_likes: int = 2000, days: int = 7, limit: int = 50):
        """Top posts only. A full timeline of 36k posts is noise; the ~10 posts
        above a like threshold are the actual story."""
        end = now_safe()
        q = f"{query} {C.OP_MIN_LIKES}:{min_likes}"
        rows, _ = self.search(q, end - timedelta(days=days), end, max_results=limit)
        rows.sort(key=lambda r: -r["public_metrics"]["like_count"])
        return rows

    def report(self) -> str:
        return (f"x: {self.search_calls} searches, {self.counts_calls} counts, "
                f"{self.posts_read} posts, ${self.spend:.3f}")
