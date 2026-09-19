"""Capture an explicitly selected set of public X embeds; no API keys or models.

Run from any directory with Python 3. This refreshes the saved snapshot and its
raw source payloads. It does NOT search X, establish an earliest post, or measure
platform-wide volume. Long-post embed text is retained as an excerpt, never
reconstructed from secondary reporting.
"""
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
TC = "https://techcrunch.com/2026/09/12/anthropic-ceo-outlines-plan-to-pace-the-frontier/"
CC = "https://cellcog.ai/blog/we-must-pace-the-frontier/"
ZVI = "https://thezvi.substack.com/p/we-must-pace-the-frontier"
SOURCES = [
    ("2087370436959186977", "tszzl", "Earlier phrase", "Project README, independently re-fetched from X"),
    ("2098773920774074715", "DarioAmodei", "Author announcement", "https://www.livemint.com/technology/must-slow-the-pace-down-anthropic-ceo-dario-amodei-calls-for-ai-industry-to-slow-down-or-risk-losing-control-11789229416944.html"),
    ("2098789109980332057", "elonmusk", "Reaction", TC),
    ("2098811563415150910", "sama", "Reaction", TC),
    ("2098847403134611522", "SenSanders", "Reaction", CC),
    ("2098909516582490602", "demishassabis", "Reaction", CC),
    ("2099145338678378958", "timhwang", "Reaction", ZVI),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def collect():
    posts, raw_payloads = [], []
    for tweet_id, expected_handle, role, discovered_via in SOURCES:
        endpoint = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=a"
        with urlopen(Request(endpoint, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
            raw = response.read()
        captured_at = utc_now()
        payload = json.loads(raw)
        user = payload.get("user", {})
        if payload.get("__typename") != "Tweet" or payload.get("id_str") != tweet_id or not payload.get("text"):
            raise RuntimeError(f"No usable tweet payload for {tweet_id}; snapshot not refreshed")
        if user.get("screen_name", "").lower() != expected_handle.lower():
            raise RuntimeError(f"Unexpected author for {tweet_id}; inspect manually before refreshing")
        published_at = payload["created_at"]
        embedded_ms = (int(tweet_id) >> 22) + 1288834974657
        actual_ms = datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp() * 1000
        if abs(actual_ms - embedded_ms) > 1000:
            raise RuntimeError(f"Timestamp/ID mismatch for {tweet_id}")
        capture = {
            "method": "X public syndication embed",
            "endpoint": endpoint,
            "capturedAt": captured_at,
            "textIsExcerpt": bool(payload.get("note_tweet")),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rawFile": f"raw/{tweet_id}.json",
            "discoveredVia": discovered_via,
        }
        post = {
            "id": tweet_id, "postId": tweet_id,
            "author": f"{user['name']} · @{user['screen_name']}",
            "authorId": user.get("id_str"), "handle": user["screen_name"],
            "text": payload["text"], "publishedAt": published_at,
            "url": f"https://x.com/{user['screen_name']}/status/{tweet_id}",
            "role": role, "capture": capture,
        }
        if isinstance(payload.get("favorite_count"), int):
            post["likes"] = payload["favorite_count"]
        quoted = payload.get("quoted_tweet")
        if isinstance(quoted, dict) and quoted.get("id_str"):
            post["quotedPostId"] = quoted["id_str"]
        posts.append(post)
        raw_payloads.append((ROOT / capture["rawFile"], raw))
        print(f"Captured @{user['screen_name']} {tweet_id}: {published_at}; excerpt={capture['textIsExcerpt']}")
        time.sleep(1.1)

    snapshot = {
        "schemaVersion": 1,
        "kind": "curated-source-snapshot",
        "capturedAt": utc_now(),
        "primaryPostId": "2098773920774074715",
        "essayUrl": "https://darioamodei.com/post/we-must-pace-the-frontier",
        "selection": "Author announcement, an earlier phrase match, and selected publicly linked reactions. Purposive selection, not an exhaustive search or random sample.",
        "limitations": [
            "This records source payloads, not a production pipeline execution or model predictions.",
            "Replay timing and editorial explanations are prepared for the demo, not recorded execution timings.",
            "Timeline counts cover only the saved posts; no X search-volume measurements were collected.",
            "Engagement is a point-in-time snapshot and will change. Popular ranks only the selected posts.",
            "Long posts may be truncated by X's embed endpoint; marked excerpts are never reconstructed.",
            "The earlier phrase is not established as the first use, nor as the origin of Dario's essay.",
            "Chronology and reactions do not establish copying, independent corroboration, or implementation of commitments.",
        ],
        "posts": sorted(posts, key=lambda post: post["publishedAt"]),
    }
    # Fetch and validate everything before replacing the existing snapshot.
    for path, raw in raw_payloads:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (ROOT / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved {len(posts)} posts. No paid API, search, or model calls were made.")


if __name__ == "__main__":
    collect()
