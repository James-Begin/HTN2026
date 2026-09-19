"""Choose the accept threshold on held-out data, never on the gate.

Picking the threshold that makes the release gate pass is fitting to the gate, so the
threshold is chosen on a validation split and only then applied to the gate.

Doing that honestly exposed a real cost of training English-only. On an ENGLISH
validation split, xenc-v2's best-F1 threshold is 0.9729. The gate's passing band is
0.5874 to 0.8006, so 0.9729 sits above it and the Arabic pair ptf-03, at 0.8006,
fails. The model can separate every gate at 0.694, but English-only validation cannot
find that threshold, because it contains no cross-lingual pair to hold it down.

The fix does not require retraining. Calibration is inference-only, so the threshold
can be chosen on a MIXED validation split while training data stays English-focused.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import metrics as M
from eval.dataset import LABELS, POSITIVE_LABELS
from train.data import load_rows, split_by_day


def score_rows(path, rows, batch_size=64, max_length=256):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForSequenceClassification.from_pretrained(path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.eval().to(device)
    order = [model.config.id2label[i] for i in range(len(LABELS))]
    if order != LABELS:
        raise RuntimeError(f"id2label {order} != {LABELS}")
    pos_idx = [LABELS.index(l) for l in sorted(POSITIVE_LABELS)]
    out = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        enc = tok([r["reference"] for r in chunk], [r["candidate"] for r in chunk],
                  padding=True, truncation=True, max_length=max_length,
                  return_tensors="pt").to(device)
        with torch.no_grad():
            probs = torch.softmax(model(**enc).logits.float(), dim=-1)
        for j, r in enumerate(chunk):
            out.append((float(probs[j, pos_idx].sum()),
                        1 if r["label"] in POSITIVE_LABELS else 0))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="calibrate the accept threshold")
    ap.add_argument("--path", required=True, help="checkpoint directory")
    ap.add_argument("--gate", default=None, help="a saved eval run, to report the band")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-share", type=float, default=0.15)
    args = ap.parse_args(argv)

    for label, english_only in (("english-only", True), ("mixed languages", False)):
        rows = load_rows(english_only=english_only)
        _, val, rep = split_by_day(rows, val_share=args.val_share, seed=args.seed)
        xl = sum(1 for r in val if (r.get("source") or {}).get("cross_lingual"))
        scored = score_rows(args.path, val)
        best = M.best_threshold(scored)
        pos = [s for s, g in scored if g]
        neg = [s for s, g in scored if not g]
        print(f"\n  {label}: {len(val)} val rows, {xl} cross-lingual")
        print(f"    best-F1 threshold {best['threshold']:.4f}  F1 {best['f1']:.4f}  "
              f"precision {best['precision']:.4f}  recall {best['recall']:.4f}")
        print(f"    ROC AUC {M.roc_auc(pos, neg):.4f}  "
              f"robust separation {M.robust_separation(pos, neg):+.4f}")
        globals().setdefault("_thr", {})[label] = best["threshold"]

    if args.gate and os.path.exists(args.gate):
        from eval import gates as G
        blob = json.load(open(args.gate))
        sc = {c["id"]: c["score"] for c in blob["cases"]}
        un = {k: sc[k] for k in G.UNLOCK_PAIRS if k in sc}
        rg = {k: sc[k] for k in G.REGRESSION_PAIRS if k in sc}
        lo, hi = min(un.values()), max(rg.values())
        print(f"\n  gate passing band: {hi:.4f} .. {lo:.4f}  (gap {lo - hi:+.4f})")
        for label, thr in globals()["_thr"].items():
            inside = hi < thr <= lo
            up = sum(1 for v in un.values() if v >= thr)
            rp = sum(1 for v in rg.values() if v < thr)
            print(f"    threshold from {label:<16s} {thr:.4f}  "
                  f"{'INSIDE' if inside else 'outside'} the band  ->  "
                  f"unlock {up}/{len(un)}, regression {rp}/{len(rg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
