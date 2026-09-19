"""Join hand labels back onto the review file and write eval/holdout.jsonl.

The model score and machine label were withheld during labelling and are joined only
here, so the labels cannot have been anchored by them. Agreement is reported
afterwards as a measurement, not used as a correction.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.dataset import LABEL_INDEX, POSITIVE_LABELS  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", nargs="+", required=True)
    ap.add_argument("--review", default="eval/review.jsonl")
    ap.add_argument("--key", default="eval/review.key.jsonl")
    ap.add_argument("--out", default="eval/holdout.jsonl")
    args = ap.parse_args(argv)

    labels = {}
    for pat in args.labels:
        for path in sorted(glob.glob(pat)):
            labels.update(json.load(open(path)))

    review = {str(json.loads(l)["n"]): json.loads(l) for l in open(args.review)}
    key = {str(json.loads(l)["n"]): json.loads(l) for l in open(args.key)}
    missing = [n for n in review if n not in labels]
    if missing:
        sys.exit(f"unlabelled: {sorted(missing, key=int)[:20]}")

    rows, agree_exact, agree_bin, n = [], 0, 0, 0
    conf_matrix = {}
    for num, rec in sorted(review.items(), key=lambda kv: int(kv[0])):
        gold, confidence, note = labels[num]
        if gold not in LABEL_INDEX:
            sys.exit(f"row {num}: unknown label {gold!r}")
        k = key[num]
        machine = k["machine_label"]
        n += 1
        agree_exact += machine == gold
        agree_bin += (machine in POSITIVE_LABELS) == (gold in POSITIVE_LABELS)
        conf_matrix.setdefault(gold, Counter())[machine] += 1
        rows.append({
            "id": rec["id"], "reference": rec["reference"], "candidate": rec["candidate"],
            "label": gold, "confidence": confidence, "note": note,
            "source": {**k["source"], "machine_label": machine,
                       "withheld_model_score": k["model_score"]},
        })

    with open(args.out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"  {len(rows)} hand-labelled pairs -> {args.out}")
    print("  classes: " + ", ".join(f"{k}={v}" for k, v in
                                    Counter(r["label"] for r in rows).most_common()))
    print("  confidence: " + ", ".join(f"{k}={v}" for k, v in
                                       Counter(r["confidence"] for r in rows).most_common()))
    print(f"\n  agreement with the pipeline labeller (measured, not used):")
    print(f"    exact 5-way : {agree_exact / n:.1%}")
    print(f"    binary same : {agree_bin / n:.1%}")
    print("\n  where the labeller disagreed (gold -> what it said):")
    for gold, c in sorted(conf_matrix.items()):
        wrong = {k: v for k, v in c.items() if k != gold}
        if wrong:
            print(f"    {gold:<16s} {dict(sorted(wrong.items(), key=lambda kv: -kv[1]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
