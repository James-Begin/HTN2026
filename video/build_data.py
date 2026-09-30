"""Prepare a compact, deterministic animation dataset from checked-in captures."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "demo" / "recordings"
SEED_ID = "2098773920774074715"
FEATURES = json.loads((RECORDINGS / "conversation-space.json").read_text())["layouts"][SEED_ID]["features"]
CAPTURE = json.loads((RECORDINGS / "sequitor-live.json").read_text())
HUMOR = json.loads((RECORDINGS / "dario-humor.json").read_text())


def stamp(post: dict) -> float:
    try:
        return datetime.fromisoformat(post["publishedAt"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return float("nan")


def feature_for(post: dict) -> dict | None:
    saved = FEATURES.get(post["id"])
    if saved:
        return saved
    if all(isinstance(post.get(key), (int, float)) for key in ("spaceScore", "spaceY", "spaceZ")):
        return {
            "cosine": post["spaceScore"],
            "y": post["spaceY"],
            "z": post["spaceZ"],
        }
    return None


def main() -> None:
    seed = CAPTURE["seedPost"]
    seed_time = stamp(seed)
    by_id = {
        post["id"]: post
        for post in [*CAPTURE["posts"], *HUMOR["posts"], seed]
        if post.get("id") and post.get("text") and math.isfinite(stamp(post)) and feature_for(post)
    }
    candidates = [
        post for post in by_id.values()
        if post["id"] == SEED_ID or stamp(post) >= seed_time
    ]
    chosen: dict[str, dict] = {}

    def add(post: dict | None) -> None:
        if post and post["id"] not in chosen and len(chosen) < 165:
            chosen[post["id"]] = post

    # Give the first arrivals a real story beat: announcement, paraphrase,
    # reaction, and the joke that a strict same-claim filter would miss.
    priority = [
        SEED_ID, "2098776460127334538", "2098811563415150910",
        "2098789109980332057", "2098847403134611522", "2098909516582490602",
    ]
    for post_id in priority:
        add(by_id.get(post_id))
    ranked = sorted(candidates, key=lambda post: (-(post.get("likes") or 0), stamp(post), post["id"]))
    for post in ranked[:90]:
        add(post)
    directly_linked = [
        post for post in ranked
        if post.get("parentId") == SEED_ID or post.get("quotedPostId") == SEED_ID
    ]
    for post in directly_linked[:45]:
        add(post)
    chronological = sorted(candidates, key=lambda post: (stamp(post), post["id"]))
    stride = max(1, len(chronological) // 65)
    for post in chronological[::stride]:
        add(post)
    for post in chronological:
        add(post)
    selected = list(chosen.values())
    # Match the app's flow-time view: preserve publication order while
    # compressing empty gaps so the final camera frame uses its full width.
    time_rank = {
        post["id"]: rank
        for rank, post in enumerate(sorted(selected, key=lambda item: (stamp(item), item["id"])))
    }

    placed: list[tuple[float, float]] = []
    nodes = []
    for order, post in enumerate(selected):
        feature = feature_for(post)
        assert feature is not None
        progress = time_rank[post["id"]] / max(1, len(selected) - 1)
        x = 310 if post["id"] == SEED_ID else 360 + 1050 * progress
        # A quarter-turn of the saved Y/Z semantic plane is distance
        # preserving and balances this capture above and below the reference.
        y = 515 - float(feature["z"]) * 500 + float(feature["y"]) * 45
        y = min(850, max(200, y))
        if post["id"] != SEED_ID:
            for step in range(0, 16):
                offset = 0 if step == 0 else ((step + 1) // 2) * 18 * (1 if step % 2 else -1)
                candidate_y = min(875, max(180, y + offset))
                if all(math.hypot(x - other_x, candidate_y - other_y) > 16 for other_x, other_y in placed):
                    y = candidate_y
                    break
        placed.append((x, y))
        nodes.append({
            "id": post["id"], "author": post.get("author") or post.get("handle") or "X post",
            "handle": post.get("handle") or "", "text": post["text"][:300],
            "publishedAt": post["publishedAt"], "likes": post.get("likes") or 0,
            "parentId": post.get("parentId"), "quotedPostId": post.get("quotedPostId"),
            "branch": post.get("branch") or "", "cosine": round(float(feature["cosine"]), 4),
            "x": round(x, 2), "y": round(y, 2),
            "depth": round(float(feature["z"]), 4),
            "semanticY": round(float(feature["y"]), 4),
            "order": order,
        })
    ids = {post["id"] for post in selected}
    edges = []
    for post in selected:
        for field, kind in (("parentId", "reply"), ("quotedPostId", "quote")):
            target = post.get(field)
            if target in ids and target != post["id"]:
                edges.append({"from": target, "to": post["id"], "kind": kind})
    output = {
        "seedId": SEED_ID,
        "seedText": seed["text"],
        "nodes": nodes,
        "edges": edges,
        "buckets": CAPTURE["buckets"],
        "title": CAPTURE["title"],
    }
    path = ROOT / "video" / "src" / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(nodes)} captured posts, {len(edges)} observed links → {path}")


if __name__ == "__main__":
    main()
