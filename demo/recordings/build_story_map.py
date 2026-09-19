"""Annotate a bounded recorded sample with Baseten Model APIs.

Run from the repository root with ``python3 demo/recordings/build_story_map.py``.
The API key stays in .env; only public post IDs, excerpts, and model labels are saved.
Repeated runs reuse the checkpoint in work/ rather than paying for the same batch.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from claimtrace.baseten import HostedLLM  # noqa: E402
from sequitor_server import load_local_env  # noqa: E402

CAPTURE = ROOT / "demo" / "recordings" / "sequitor-live.json"
OUTPUT = ROOT / "demo" / "recordings" / "sequitor-story.json"
CHECKPOINT = ROOT / "work" / "sequitor-story-checkpoint.json"
MODEL = "openai/gpt-oss-120b"
ROLES = {"announcement", "reporting", "explanation", "adoption", "critique", "question", "humor", "other"}
STOPWORDS = set("""the and for with that this have from they them their there where which about into what when
    will would could should your you are our not has had was were who his her she its but one just more
    than much some all new now out can via https http com amp dario amodei anthropic frontier pace
    pacing ai post posts like get getting see use does really because after before only very same much
    we must an to of in on at is it as by a i he be do or if so us my me we rt""".split())


def posts_in_capture(capture: dict) -> dict[str, dict]:
    posts = {str(post["id"]): post for post in capture.get("posts", [])}
    for period in capture.get("savedPeriods", {}).values():
        for post in period.get("posts", []):
            posts[str(post["id"])] = post
    seed = capture.get("seedPost")
    if seed:
        posts[str(seed["id"])] = {**posts.get(str(seed["id"]), {}), **seed}
    return posts


def select_posts(capture: dict, posts: dict[str, dict], limit: int = 150) -> list[dict]:
    seed_id = str(capture.get("seedPost", {}).get("id") or "")
    linked = {seed_id}
    for post in posts.values():
        for field in ("parentId", "quotedPostId"):
            target = str(post.get(field) or "")
            if target in posts:
                linked.update((str(post["id"]), target))
    for post in posts.values():
        if post.get("scope") == "saved source":
            linked.add(str(post["id"]))

    def score(post: dict) -> tuple[float, str]:
        text = str(post.get("text") or "").casefold()
        words = ("dario", "anthropic", "pace the frontier", "pacing the frontier",
                 "independent evaluator", "slow down", "third-party evaluator")
        relevance = sum(term in text for term in words)
        return (relevance * 8 + math.log1p(post.get("likes") or 0), str(post["id"]))

    extras = sorted((post for post in posts.values() if str(post["id"]) not in linked),
                    key=score, reverse=True)
    chosen = [posts[id] for id in linked if id in posts]
    chosen += extras[:max(0, limit - len(chosen))]
    return sorted(chosen, key=lambda post: (post.get("publishedAt") or "", str(post["id"])))[:limit]


def wording_edges(selected: list[dict]) -> list[dict]:
    """Sparse earlier/later similarities, for navigation only, never causal links."""
    docs = []
    for post in selected:
        text = re.sub(r"https?://\S+|@\w+", " ", str(post.get("text") or "").casefold())
        docs.append([word for word in re.findall(r"[a-z][a-z0-9'-]{2,}", text)
                     if word not in STOPWORDS and len(word) >= 3])
    frequency = Counter(word for words in docs for word in set(words))
    total = len(docs)
    vectors = []
    for words in docs:
        counts = Counter(words)
        weighted = {word: (1 + math.log(count)) * math.log((total + 1) / (frequency[word] + 1))
                    for word, count in counts.items() if frequency[word] <= total * .65}
        norm = math.sqrt(sum(weight * weight for weight in weighted.values())) or 1
        vectors.append({word: weight / norm for word, weight in weighted.items()})

    observed = {(str(post["id"]), str(post.get(field)))
                for post in selected for field in ("parentId", "quotedPostId") if post.get(field)}
    edges = []
    for later in range(1, len(selected)):
        current = selected[later]
        candidates = []
        for earlier in range(later):
            previous = selected[earlier]
            if (str(current["id"]), str(previous["id"])) in observed:
                continue
            if not vectors[later] or not vectors[earlier]:
                continue
            shared = vectors[later].keys() & vectors[earlier].keys()
            if len(shared) < 2:
                continue
            cosine = sum(vectors[later][word] * vectors[earlier][word] for word in shared)
            if cosine < .24:
                continue
            terms = sorted(shared, key=lambda word: vectors[later][word] * vectors[earlier][word], reverse=True)[:3]
            candidates.append((cosine, earlier, terms))
        candidates.sort(reverse=True)
        # Prefer a substantial earlier post over a near duplicate of the seed.
        for cosine, earlier, terms in candidates[:2]:
            edges.append({"source": str(selected[earlier]["id"]), "target": str(current["id"]),
                          "cosine": round(cosine, 4), "model": "TF-IDF cosine",
                          "sharedTerms": terms})
    return edges


def main() -> None:
    load_local_env()
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise SystemExit("BASETEN_API_KEY is unavailable")
    capture = json.loads(CAPTURE.read_text())
    posts = posts_in_capture(capture)
    selected = select_posts(capture, posts)
    selected_ids = {str(post["id"]) for post in selected}
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    annotations = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {}
    model = HostedLLM(key, model=MODEL)
    missing = [post for post in selected if str(post["id"]) not in annotations]
    for offset in range(0, len(missing), 20):
        batch = missing[offset:offset + 20]
        payload = [{"id": str(post["id"]), "text": str(post.get("text") or "")[:430]}
                   for post in batch]
        answer = model.json_call(
            "You organize an X discussion for a reader. For each supplied post, return its "
            "communicative role using only the text. Roles: announcement, reporting, explanation, "
            "adoption, critique, question, humor, other. Reporting means relaying information; "
            "adoption means endorsing or committing to the proposal. A post may be serious or funny; "
            "choose its dominant role. Return JSON only: "
            "{\"posts\":[{\"id\":\"exact supplied id\",\"role\":\"allowed role\","
            "\"focus\":\"short topic phrase grounded in that post\"}]}. "
            "Do not claim truth, causal influence, or facts absent from the text.",
            json.dumps({"posts": payload}, ensure_ascii=False), max_tokens=5200,
        )
        valid = {row["id"]: row for row in answer.get("posts", [])
                 if isinstance(row, dict) and isinstance(row.get("id"), str)}
        for post in batch:
            post_id = str(post["id"])
            row = valid.get(post_id, {})
            role = row.get("role") if row.get("role") in ROLES else "other"
            annotations[post_id] = {"role": role, "focus": str(row.get("focus") or "")[:72]}
        CHECKPOINT.write_text(json.dumps(annotations, ensure_ascii=False, indent=2) + "\n")
        print(f"Annotated {min(offset + len(batch), len(missing))}/{len(missing)} new posts")

    output = {
        "seedId": str(capture.get("seedPost", {}).get("id") or ""),
        "captureSha256": hashlib.sha256(CAPTURE.read_bytes()).hexdigest(),
        "method": "Baseten hosted model post-level grouping; labels are suggestions, not verified facts",
        "model": MODEL,
        "selectedPostIds": [str(post["id"]) for post in selected],
        "annotations": {id: annotations[id] for id in selected_ids},
        "similarityEdges": wording_edges(selected),
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(selected)} selected posts; {model.report()}")


if __name__ == "__main__":
    main()
