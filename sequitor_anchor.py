"""Pure helpers for resolving the conversation behind an entry post."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit


_STATUS_PATH = re.compile(r"/(?:status|statuses)/(\d+)(?:/|$)")
_SNOWFLAKE = re.compile(r"[1-9]\d{14,21}")


def tweet_id_from_url(value: str) -> str | None:
    """Return a numeric status id from an X/Twitter status URL."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower() not in {
        "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"
    }:
        return None
    match = _STATUS_PATH.search(parsed.path)
    return match.group(1) if match else None


def looks_like_snowflake(value: Any) -> bool:
    """Apply a conservative shape check without making a network request."""
    return isinstance(value, (str, int)) and bool(_SNOWFLAKE.fullmatch(str(value)))


def conversation_anchor(post: Mapping[str, Any],
                        fetch_post: Callable[[str], Mapping[str, Any] | None],
                        max_hops: int = 4) -> dict[str, Any]:
    """Walk quote edges before reply edges, stopping safely on gaps or cycles."""
    entry = post
    anchor = post
    visited = {str(post.get("id") or "")}
    hops = 0
    followed_quote = False

    while hops < max(0, max_hops):
        candidates = (
            ("quote", anchor.get("quotedPostId")),
            ("reply", anchor.get("parentId")),
        )
        next_post = None
        edge = None
        for candidate_edge, candidate_id in candidates:
            candidate_id = str(candidate_id or "")
            if not candidate_id or candidate_id in visited:
                continue
            try:
                fetched = fetch_post(candidate_id)
            except Exception:
                fetched = None
            if not fetched:
                continue
            fetched_id = str(fetched.get("id") or "")
            if fetched_id != candidate_id or fetched_id in visited:
                continue
            next_post, edge = fetched, candidate_edge
            break
        if next_post is None:
            break
        anchor = next_post
        visited.add(str(anchor["id"]))
        hops += 1
        followed_quote = followed_quote or edge == "quote"

    method = "self" if hops == 0 else ("quote-walk" if followed_quote else "reply-walk")
    return {"anchor": anchor, "entry": entry, "hops": hops, "method": method}


def choose_semantic_anchor(entry_post: Mapping[str, Any], suggestion: Mapping[str, Any],
                           fetch_post: Callable[[str], Mapping[str, Any] | None]):
    """Accept a suggested status only when its id is plausible and fetchable."""
    candidate = suggestion.get("referenced_post_id")
    if not looks_like_snowflake(candidate):
        candidate = tweet_id_from_url(str(suggestion.get("referenced_url") or ""))
    if not looks_like_snowflake(candidate):
        return entry_post
    candidate = str(candidate)
    if candidate == str(entry_post.get("id") or ""):
        return entry_post
    try:
        fetched = fetch_post(candidate)
    except Exception:
        return entry_post
    if not fetched or str(fetched.get("id") or "") != candidate:
        return entry_post
    return fetched
