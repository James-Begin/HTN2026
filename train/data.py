"""Training data assembly for the English claim-equivalence cross-encoder.

Two decisions here are load-bearing.

**The split is by DAY, not by row.** 21% of posts appear in more than one pair, and
one post appears in 14. A random row split would put the same post text on both sides
of the boundary and the validation score would be inflated by memorisation. Days are
the natural unit because a day is roughly an event, and pairs only form within a
one-day window, so splitting on days separates events as well as posts. Any pair that
still straddles the boundary is dropped rather than assigned.

**The eval set is never touched.** `eval/pairs.jsonl` is hand-labelled and is the
release gate. Everything here is `machine` or `structural` and is training data only.
Measured label agreement is 74% exact against 94% binary, so these labels are useful
supervision and not ground truth.
"""
import json
import os
import random
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.dataset import LABELS, LABEL_INDEX, POSITIVE_LABELS  # noqa: E402

MINE_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "mine", "out")
DEFAULT_SOURCES = [
    # Re-labelled with the hybrid labeller: `meta` accuracy 14% -> 89% measured on
    # 199 hand labels, which moved 3,843 rows into `meta` from `incidental` and
    # `unrelated`. train-all.jsonl is the pre-relabel file, kept for the ablation.
    os.path.join(MINE_OUT, "train-relabelled.jsonl"),
    os.path.join(MINE_OUT, "train-verbatim.jsonl"),
    # Added after the first checkpoint broke two gates. Both are structural, free, and
    # target a specific measured failure rather than adding generic volume:
    #   collisions  ssi-05 became a false accept at 0.5415 (acronym referring to a
    #               different entity), because the labeller mislabels that shape too
    #   headlines   ptf-02 got WORSE, 0.2611 -> 0.0527 (short title-plus-link against
    #               a long announcement), a length asymmetry the truncation pairs miss
    os.path.join(MINE_OUT, "train-collisions.jsonl"),
    # Scoping to English cut `same_paraphrase` from 6,263 rows to 1,364, because most
    # paraphrase pairs were cross-lingual: different-language outlets share only entity
    # names, so their pairs sit at low overlap and read as paraphrases. Loosening the
    # same-language join from 3 shared rare tokens to 2 exposed 6,296 unlabelled English
    # candidates, which the hybrid labeller turned into 3,410 more paraphrase rows.
    os.path.join(MINE_OUT, "train-en-extra.jsonl"),
    os.path.join(MINE_OUT, "train-headlines.jsonl"),
]

VAL_DAY_SHARE = 0.15


def load_rows(paths: List[str] = None, english_only: bool = True) -> List[dict]:
    paths = paths or DEFAULT_SOURCES
    rows, seen = [], set()
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            lines = fh.readlines()
        for line in lines:
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["reference"], r["candidate"])
            if key in seen or r["reference"] == r["candidate"]:
                continue
            src = r.get("source") or {}
            if english_only and not (src.get("a_lang") == "en" and src.get("b_lang") == "en"):
                continue
            if r["label"] not in LABEL_INDEX:
                continue
            seen.add(key)
            rows.append(r)
    return rows


def _day_of(row: dict) -> str:
    src = row.get("source") or {}
    return src.get("a_day") or src.get("b_day") or ""


def split_by_day(rows: List[dict], val_share: float = VAL_DAY_SHARE,
                 seed: int = 0) -> Tuple[List[dict], List[dict], dict]:
    """Hold out whole days. Returns (train, val, report).

    Days are shuffled rather than taken from the end, because the tail of the window
    is where outlet coverage thins out and a chronological holdout would validate on
    systematically sparser data.
    """
    rng = random.Random(seed)
    days = sorted({_day_of(r) for r in rows if _day_of(r)})
    rng.shuffle(days)
    n_val = max(1, int(len(days) * val_share))
    val_days = set(days[:n_val])

    train = [r for r in rows if _day_of(r) not in val_days]
    val = [r for r in rows if _day_of(r) in val_days]

    # Post-level leakage check. A pair whose two posts sit on different days can
    # straddle the boundary, so verify rather than assume.
    train_uris = set()
    for r in train:
        src = r["source"]
        train_uris.add(src.get("a_uri"))
        train_uris.add(src.get("b_uri"))
    clean_val, leaked = [], 0
    for r in val:
        src = r["source"]
        if src.get("a_uri") in train_uris or src.get("b_uri") in train_uris:
            leaked += 1
            continue
        clean_val.append(r)

    report = {
        "days_total": len(days), "days_val": len(val_days),
        "train_rows": len(train), "val_rows": len(clean_val),
        "val_dropped_for_leakage": leaked,
        "train_labels": dict(Counter(r["label"] for r in train).most_common()),
        "val_labels": dict(Counter(r["label"] for r in clean_val).most_common()),
    }
    return train, clean_val, report


def class_weights(rows: List[dict], cap: float = 8.0) -> List[float]:
    """Inverse-frequency weights, capped.

    Uncapped weights are dangerous here. `same_verbatim` is rare enough that its raw
    inverse frequency would dominate the loss and the model would learn to shout that
    class. Capping keeps the rare classes trainable without letting them take over.
    """
    counts = Counter(r["label"] for r in rows)
    total = sum(counts.values())
    weights = []
    for label in LABELS:
        n = counts.get(label, 0)
        w = (total / (len(LABELS) * n)) if n else 1.0
        weights.append(min(w, cap))
    return weights


def to_examples(rows: List[dict]) -> List[dict]:
    """Flatten to what the collator needs, including the binary target.

    The binary target is carried explicitly rather than derived at loss time so the
    objective is legible: measured label agreement is 94% on same-versus-not and only
    74% on the subtype, so the binary signal is the trustworthy one.
    """
    out = []
    for r in rows:
        out.append({
            "reference": r["reference"],
            "candidate": r["candidate"],
            "label": LABEL_INDEX[r["label"]],
            "is_same": 1.0 if r["label"] in POSITIVE_LABELS else 0.0,
            "id": r.get("id", ""),
        })
    return out


def summary(rows: List[dict]) -> str:
    labs = Counter(r["label"] for r in rows)
    srcs = Counter((r.get("source") or {}).get("kind", "?") for r in rows)
    lines = [f"{len(rows)} English rows"]
    for label in LABELS:
        n = labs.get(label, 0)
        lines.append(f"  {label:<16s} {n:>5d}  {n / max(len(rows), 1):>5.1%}")
    lines.append("  sources: " + ", ".join(f"{k}={v}" for k, v in srcs.most_common()))
    return "\n".join(lines)
