"""Keyless Bluesky reader.

Why Bluesky at all: X bills per row returned, so a mined corpus of any size costs
real money. Bluesky's AppView costs nothing. Same events, same day, free.

Measured constraints on the public AppView, 2026-09-14:
  * `app.bsky.feed.searchPosts` is 403'd at the CDN edge without auth. The block
    page comes from BunnyCDN, not from Bluesky's API, so it is deliberate and no
    amount of retrying helps. Search is unavailable to us.
  * `app.bsky.feed.getAuthorFeed` and `app.bsky.actor.getProfile` DO work keyless
    and paginate with a cursor. So we cannot ask "who said X", only "what did this
    account say". That is why mining is account-driven rather than query-driven.
  * `record.langs` was absent on every Reuters post sampled, so per-post language
    is unreliable. Use the account's editorial language instead.
  * Outlets link their OWN article, and Reuters shortens to `reut.rs`. Two outlets
    covering one event therefore share NO url. Grouping on links does not work
    across outlets; that was the original plan and the data killed it.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

APPVIEW = "https://public.api.bsky.app/xrpc"
USER_AGENT = "claimtrace-research/0.1"

# Bluesky publishes a generous per-IP limit. We are a research script reading
# public feeds, so stay well under it and be a good citizen about it.
MIN_INTERVAL = 0.25
PAGE_LIMIT = 100          # the endpoint's maximum


@dataclass
class Post:
    """One post, flattened to what pairing actually needs."""
    uri: str
    handle: str
    lang: str
    created_at: str
    text: str
    title: str = ""          # the linked article's headline
    description: str = ""    # the linked article's lede
    url: str = ""
    langs: List[str] = field(default_factory=list)
    # English rendering of a non-Latin post, used ONLY to compute the candidate
    # join. Never stored in a training pair and never used for language detection.
    translation: str = ""

    @property
    def id(self) -> str:
        """Stable short id: the rkey at the end of the at:// uri."""
        return self.uri.rsplit("/", 1)[-1]

    @property
    def day(self) -> str:
        return self.created_at[:10]

    def as_dict(self) -> dict:
        return {"uri": self.uri, "id": self.id, "handle": self.handle,
                "lang": self.lang, "created_at": self.created_at, "text": self.text,
                "title": self.title, "description": self.description,
                "url": self.url, "langs": self.langs,
                "translation": self.translation}

    @staticmethod
    def from_dict(d: dict) -> "Post":
        return Post(uri=d["uri"], handle=d["handle"], lang=d["lang"],
                    created_at=d["created_at"], text=d["text"],
                    title=d.get("title", ""), description=d.get("description", ""),
                    url=d.get("url", ""), langs=d.get("langs") or [],
                    translation=d.get("translation", ""))

    @property
    def join_text(self) -> str:
        """What the candidate join tokenises. The translation when there is one,
        otherwise the real text. Arabic shares no tokens with English, so without
        this a non-Latin post pairs with nothing at all."""
        return self.translation or self.claim_text

    @property
    def claim_text(self) -> str:
        """What we treat as the claim.

        The post text is usually the headline with a shortener glued on the end. The
        embed title is the same headline without the url noise, so prefer it when
        present and fall back to the text.
        """
        base = (self.title or self.text or "").strip()
        return base


class Bluesky:
    """Read-only, unauthenticated. Tracks calls so a run's cost is visibly zero."""

    def __init__(self, verbose: bool = False):
        self.calls = 0
        self.verbose = verbose
        self._last = 0.0

    def _get(self, method: str, **params) -> dict:
        gap = time.time() - self._last
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        url = f"{APPVIEW}/{method}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read())
                self._last = time.time()
                self.calls += 1
                return body
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                detail = e.read()[:160].decode(errors="replace")
                if e.code == 403:
                    raise RuntimeError(
                        f"{method} is blocked without auth at the CDN edge. "
                        "searchPosts behaves this way; use getAuthorFeed."
                    ) from None
                raise RuntimeError(f"bluesky {method} HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"bluesky {method}: retries exhausted")

    # ------------------------------------------------------------------ reading
    def profile(self, handle: str) -> dict:
        return self._get("app.bsky.actor.getProfile", actor=handle)

    def author_feed(self, handle: str, lang: str = "", pages: int = 5,
                    since: str = "", emit=None):
        """Yield Posts newest-first. `since` is an ISO date; stop once older.

        Replies are excluded. A reply is a conversation turn rather than a
        headline, and for an outlet account it is usually a thread continuation
        that repeats the parent, which would manufacture fake verbatim pairs.
        """
        cursor, seen = None, 0
        for page in range(pages):
            params = {"actor": handle, "limit": PAGE_LIMIT,
                      "filter": "posts_no_replies"}
            if cursor:
                params["cursor"] = cursor
            d = self._get("app.bsky.feed.getAuthorFeed", **params)
            items = d.get("feed") or []
            if not items:
                return
            stop = False
            for item in items:
                post = self._flatten(item, handle, lang)
                if post is None:
                    continue
                if since and post.created_at[:10] < since:
                    stop = True
                    break
                seen += 1
                yield post
            if emit:
                emit(handle, page + 1, seen)
            cursor = d.get("cursor")
            if stop or not cursor:
                return

    @staticmethod
    def _flatten(item: dict, handle: str, lang: str) -> Optional[Post]:
        post = item.get("post") or {}
        rec = post.get("record") or {}
        if rec.get("$type") not in (None, "app.bsky.feed.post"):
            return None
        # A repost surfaces in the feed with a `reason`. It is the same text by a
        # different hand, which is a verbatim pair we already get for free from X
        # retweets, so skip it rather than double-count.
        if item.get("reason"):
            return None
        embed = rec.get("embed") or {}
        ext = embed.get("external") or {}
        url = ext.get("uri") or ""
        if not url:
            for facet in rec.get("facets") or []:
                for feat in facet.get("features") or []:
                    if feat.get("uri"):
                        url = feat["uri"]
                        break
        return Post(
            uri=post.get("uri", ""), handle=handle, lang=lang,
            created_at=rec.get("createdAt", "") or post.get("indexedAt", ""),
            text=(rec.get("text") or "").strip(),
            title=(ext.get("title") or "").strip(),
            description=(ext.get("description") or "").strip(),
            url=url, langs=rec.get("langs") or [],
        )

    def report(self) -> str:
        return f"bluesky: {self.calls} requests, $0.00"


# ------------------------------------------------------------------- persistence
def save(posts, path: str) -> int:
    with open(path, "w") as fh:
        for p in posts:
            fh.write(json.dumps(p.as_dict(), ensure_ascii=False) + "\n")
    return len(posts)


def load(path: str) -> List[Post]:
    with open(path) as fh:
        return [Post.from_dict(json.loads(l)) for l in fh if l.strip()]
