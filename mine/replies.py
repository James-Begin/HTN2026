"""Replies as a source of `meta` pairs. Free, keyless.

Mining outlet feeds produced 1,466 `same_paraphrase` rows and only 34 `meta`. That
is structural, not bad luck: newsrooms report events, they do not post commentary
about each other's claims. So the feed corpus cannot teach the `meta` class.

Replies can. A reply to a news post is almost always ABOUT the claim rather than an
instance of it, and crucially it is where DENIALS live. That is the single most
expensive confusion this model can make: a verify run counts corroborating posts, so
a reply reading "no public reports confirm any of this" scoring as a match inverts
the conclusion. `meta` is the class that prevents it and the class we had least data
for.

Orientation matters and is fixed here: `reference` is the root post's claim and
`candidate` is the reply. That is the same direction as the hand-labelled pairs in
eval/pairs.jsonl, where a "source?" reply and a disputing reply both sit as
candidates against the original claim.

Replies are NOT assumed to be meta. Many restate the claim, plenty are unrelated
venting, and some are jokes. They go through the same labeller as everything else;
what this module changes is the prior, not the label.
"""
import urllib.parse
from typing import List

from .bluesky import Bluesky, Post
from .pairs import Candidate
from .text import detect_language, jaccard, tokens

# Below this many content tokens a reply carries no claim to compare: bare emoji,
# "lol", "this", a lone link. Measured on real threads, these are a large fraction.
MIN_REPLY_TOKENS = 5
MAX_REPLY_CHARS = 600


def _flatten_reply(node: dict, root_handle: str) -> Post:
    post = node.get("post") or {}
    rec = post.get("record") or {}
    author = post.get("author") or {}
    return Post(
        uri=post.get("uri", ""),
        handle=author.get("handle", "") or "unknown",
        lang="",
        created_at=rec.get("createdAt", "") or post.get("indexedAt", ""),
        text=(rec.get("text") or "").strip()[:MAX_REPLY_CHARS],
        langs=rec.get("langs") or [],
    )


def fetch(bs: Bluesky, roots: List[Post], per_root: int = 6,
          progress=None) -> List[Candidate]:
    """Pair each root post with its substantive replies.

    One request per root, so this is bounded by request count rather than by cost.
    """
    out = []
    for i, root in enumerate(roots):
        if not root.uri or not root.claim_text:
            continue
        try:
            d = bs._get("app.bsky.feed.getPostThread",
                        uri=root.uri, depth=1)
        except RuntimeError:
            continue
        thread = d.get("thread") or {}
        replies = thread.get("replies") or []
        root_toks = tokens(root.claim_text, root.description)
        root_lang = detect_language(root_toks, default=root.lang,
                                    raw=f"{root.claim_text} {root.description}")
        kept = 0
        for node in replies:
            if kept >= per_root:
                break
            rep = _flatten_reply(node, root.handle)
            if not rep.uri or not rep.text:
                continue
            # An outlet replying to itself is a thread continuation, which repeats
            # the parent and would manufacture fake verbatim pairs.
            if rep.handle == root.handle:
                continue
            rtoks = tokens(rep.text)
            if len(rtoks) < MIN_REPLY_TOKENS:
                continue
            rlang = detect_language(rtoks, default="en", raw=rep.text)
            out.append(Candidate(
                a_uri=root.uri, b_uri=rep.uri,
                a_handle=root.handle, b_handle=rep.handle,
                a_lang=root_lang, b_lang=rlang,
                a_text=root.claim_text, b_text=rep.text,
                a_day=root.day, b_day=rep.day,
                shared=len(root_toks & rtoks),
                shared_tokens=sorted(root_toks & rtoks)[:12],
                jaccard=round(jaccard(root_toks, rtoks), 4),
                overlap=0.0,
                cross_lingual=root_lang != rlang,
                near_duplicate=False,
            ))
            kept += 1
        if progress:
            progress(i + 1, len(roots), len(out))
    return out


def pick_roots(posts: List[Post], n: int = 300, seed: int = 0) -> List[Post]:
    """Prefer roots likely to have argument under them.

    Engagement is not in the feed payload, so this uses a cheap proxy: posts from
    the outlets whose audiences actually reply, spread across days so one news cycle
    does not dominate the sample.
    """
    import random
    from collections import defaultdict

    rng = random.Random(seed)
    by_day = defaultdict(list)
    for p in posts:
        if p.claim_text and p.uri:
            by_day[p.day].append(p)
    days = sorted(by_day)
    out = []
    while len(out) < n and days:
        for day in list(days):
            bucket = by_day[day]
            if not bucket:
                days.remove(day)
                continue
            out.append(bucket.pop(rng.randrange(len(bucket))))
            if len(out) >= n:
                break
    return out
