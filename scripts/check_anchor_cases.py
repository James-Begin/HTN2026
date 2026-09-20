#!/usr/bin/env python3
"""Opt-in structural anchor check against X's public syndication payload."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "anchor_cases.json"
ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=a"


def fetch(post_id):
    request = urllib.request.Request(
        ENDPOINT.format(post_id=post_id),
        headers={"User-Agent": "Sequitor anchor fixture checker"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def reference_id(post, relation):
    nested = post.get(relation)
    if not isinstance(nested, dict):
        return None
    return nested.get("id_str") or nested.get("id")


def resolve_structural(entry_id):
    current_id = entry_id
    seen = set()
    while current_id not in seen:
        seen.add(current_id)
        post = fetch(current_id)
        next_id = (
            reference_id(post, "quoted_tweet")
            or post.get("quoted_tweet_id_str")
            or post.get("in_reply_to_status_id_str")
            or reference_id(post, "parent")
        )
        if not next_id:
            return current_id
        current_id = str(next_id)
    raise RuntimeError(f"cycle detected at {current_id}")


def main():
    if os.environ.get("SEQUITOR_LIVE_ANCHOR") != "1":
        print("Live checks are off; set SEQUITOR_LIVE_ANCHOR=1 to enable.")
        return 0

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    failed = False
    for case in cases:
        try:
            resolved = resolve_structural(case["entryId"])
            matches = resolved == case["expectedAnchorId"]
            if case["kind"] == "semantic-reference":
                status = "semantic lookup required"
            else:
                status = "ok" if matches else "mismatch"
                failed = failed or not matches
            print(
                f"{case['id']}: entry={case['entryId']} "
                f"resolved={resolved} expected={case['expectedAnchorId']} "
                f"({status})"
            )
        except (OSError, urllib.error.URLError, ValueError) as error:
            failed = True
            print(f"{case['id']}: live fetch failed: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
