"""Sample mined pairs for hand labelling, BLIND to the model's score.

Why blind: the eval set's only value is being independent of everything that produced
the training labels. If pairs are labelled while their model score is visible, the set
degenerates into a confirmation of what the model already believes, and it can no
longer catch the model being confidently wrong. So this writes a review file with the
scores stripped, and the scores are joined back only after the labels are fixed.

Where the pairs come from, and why:

  * Drawn from the VALIDATION days only. Those days are already excluded from training
    by `train/data.py`, so nothing here was trained on.
  * Half from the 0.3-0.7 score band. That is where the accept decision actually
    happens and where there is almost no labelled evidence: 61% of held-out scores sit
    below 0.1 and 23% above 0.9, so 84% of existing evidence is in the easy regions
    while the boundary is nearly unmeasured.
  * Half spread across the rest, because a set made only of boundary cases would give
    a distorted view of aggregate precision and recall.
  * Stratified across sources and languages, so replies, collisions and
    headline-asymmetry pairs are all represented rather than just event pairs.

The machine label is also stripped. It is recorded separately so agreement can be
measured afterwards, which is a useful number, but it must not anchor the annotator.
"""
import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BAND = (0.30, 0.70)


def sample(scored_rows, n=180, band_share=0.5, seed=0):
    """scored_rows = [(row, score)]. Returns rows chosen for review."""
    rng = random.Random(seed)
    in_band = [(r, s) for r, s in scored_rows if BAND[0] <= s <= BAND[1]]
    out_band = [(r, s) for r, s in scored_rows if not (BAND[0] <= s <= BAND[1])]

    def stratify(pool, k):
        """Spread across (source kind, cross-lingual) so no bucket dominates."""
        buckets = defaultdict(list)
        for r, s in pool:
            src = r.get("source") or {}
            buckets[(src.get("kind"), bool(src.get("cross_lingual")))].append((r, s))
        for b in buckets.values():
            rng.shuffle(b)
        picked, keys = [], sorted(buckets, key=lambda k2: str(k2))
        while len(picked) < k and any(buckets[key] for key in keys):
            for key in keys:
                if buckets[key] and len(picked) < k:
                    picked.append(buckets[key].pop())
        return picked

    want_band = min(int(n * band_share), len(in_band))
    chosen = stratify(in_band, want_band) + stratify(out_band, n - want_band)
    rng.shuffle(chosen)
    return chosen


def write_review(chosen, path):
    """Write the file a human reads. Scores and machine labels are NOT in it."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        for i, (row, _score) in enumerate(chosen, 1):
            src = row.get("source") or {}
            fh.write(json.dumps({
                "n": i,
                "id": f"hold-{row['id']}",
                "reference": row["reference"],
                "candidate": row["candidate"],
                "label": "",                     # to be filled in by hand
                "hint_langs": f"{src.get('a_lang')}/{src.get('b_lang')}",
                "hint_source": src.get("kind"),
            }, ensure_ascii=False) + "\n")
    return len(chosen)


def write_key(chosen, path):
    """The withheld side: model score and machine label, joined back after labelling."""
    with open(path, "w") as fh:
        for i, (row, score) in enumerate(chosen, 1):
            fh.write(json.dumps({
                "n": i, "id": f"hold-{row['id']}", "model_score": score,
                "machine_label": row["label"],
                "source": row.get("source") or {},
            }, ensure_ascii=False) + "\n")
    return len(chosen)


def main(argv=None):
    ap = argparse.ArgumentParser(description="sample mined pairs for blind hand labelling")
    ap.add_argument("--path", default="runs/xenc-best", help="checkpoint, for scoring only")
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--review", default="eval/review.jsonl")
    ap.add_argument("--key", default="eval/review.key.jsonl")
    args = ap.parse_args(argv)

    from train.calibrate import score_rows
    from train.data import load_rows, split_by_day

    rows = load_rows(english_only=False)
    _, val, rep = split_by_day(rows, val_share=0.15, seed=0)
    print(f"  {len(val)} validation rows across {rep['days_val']} held-out days")
    scores = score_rows(args.path, val)
    scored = [(r, s) for r, (s, _g) in zip(val, scores)]

    chosen = sample(scored, n=args.n, seed=args.seed)
    in_band = sum(1 for _, s in chosen if BAND[0] <= s <= BAND[1])
    print(f"  sampled {len(chosen)}: {in_band} inside the {BAND[0]}-{BAND[1]} decision band")
    print("  sources: " + ", ".join(
        f"{k}={v}" for k, v in Counter((r.get('source') or {}).get('kind')
                                       for r, _ in chosen).most_common()))
    print("  cross-lingual: " + str(sum(1 for r, _ in chosen
                                        if (r.get('source') or {}).get('cross_lingual'))))
    print("  machine labels (WITHHELD from the review file): " + ", ".join(
        f"{k}={v}" for k, v in Counter(r["label"] for r, _ in chosen).most_common()))

    write_review(chosen, args.review)
    write_key(chosen, args.key)
    print(f"\n  {args.review}  <- label this, scores stripped")
    print(f"  {args.key}      <- withheld scores and machine labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
