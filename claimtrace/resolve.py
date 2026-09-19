"""Keyless tweet resolution with four distinguishable states.

The syndication endpoint is undocumented but free and unauthenticated, and it
returns strictly more information than "did this work":

    __typename == "Tweet"                          -> LIVE
    TweetTombstone, "deleted by the Post author"   -> DELETED   (id real, gone)
    TweetTombstone, "limits who can view"          -> PROTECTED (id real, locked)
    TweetTombstone, empty body                     -> GONE      (account removed)
    HTTP 404                                       -> NONEXISTENT

That distinction is the whole point for this tool. A DELETED root is a positive
finding: the post provably existed and provably no longer does, which is very
different from a fabricated id. Combined with the Snowflake decoder we can also
recover a deleted post's exact creation time without any API access at all.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from .xapi import id_to_time

SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0"

LIVE = "LIVE"
DELETED = "DELETED"
PROTECTED = "PROTECTED"
GONE = "GONE"
NONEXISTENT = "NONEXISTENT"


@dataclass
class Resolved:
    tweet_id: str
    state: str
    text: str = ""
    handle: str = ""
    author_id: str = ""
    created_at: datetime = None
    likes: int = 0
    media: list = field(default_factory=list)
    tombstone: str = ""

    @property
    def existed(self) -> bool:
        """True for every state except a fabricated id."""
        return self.state != NONEXISTENT

    @property
    def recoverable_text(self) -> bool:
        return self.state == LIVE and bool(self.text)

    def __str__(self):
        when = self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else "?"
        return f"[{self.state}] {self.tweet_id} {when} @{self.handle or '?'}"


def tweet_id_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("?")[0]


def resolve(tweet_id_or_url: str, timeout: int = 10) -> Resolved:
    tid = tweet_id_or_url
    if "/" in tid:
        tid = tweet_id_from_url(tid)
    if not tid.isdigit():
        raise ValueError(f"not a tweet id: {tweet_id_or_url!r}")

    # Free, works even when the post is gone.
    try:
        embedded_time = id_to_time(tid)
    except ValueError:
        embedded_time = None

    req = urllib.request.Request(f"{SYNDICATION}?id={tid}&token=a", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # 404 = never existed. 400 = malformed/out-of-range id, also nonexistent.
        if e.code in (400, 404):
            return Resolved(tid, NONEXISTENT, created_at=embedded_time)
        raise

    if d.get("__typename") == "TweetTombstone" or not d.get("text"):
        note = ""
        tomb = d.get("tombstone") or {}
        if isinstance(tomb, dict):
            note = ((tomb.get("text") or {}).get("text")
                    or (tomb.get("richText") or {}).get("text") or "")
        low = note.lower()
        if "deleted" in low:
            state = DELETED
        elif "limits who can view" in low or "protected" in low:
            state = PROTECTED
        else:
            state = GONE
        return Resolved(tid, state, created_at=embedded_time, tombstone=note[:200])

    user = d.get("user") or {}
    created = None
    if d.get("created_at"):
        created = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00"))
    return Resolved(
        tweet_id=tid,
        state=LIVE,
        text=d.get("text", ""),
        handle=user.get("screen_name", ""),
        # Identity must key on the immutable id: handles change. @BPGlobalPR became
        # @thededsouls, so every citation in the literature points at a dead handle
        # while the id still resolves.
        author_id=str(user.get("id_str") or user.get("id") or ""),
        created_at=created or embedded_time,
        likes=d.get("favorite_count") or 0,
        media=[m.get("media_url_https") for m in (d.get("mediaDetails") or [])],
    )
