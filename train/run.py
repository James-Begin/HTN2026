"""Train one configuration.

    .venv/bin/python -m train.run --epochs 3 --lr 2e-5 --out runs/xenc-a
    .venv/bin/python -m train.run --describe          # data only, no GPU

After training, score the checkpoint against the release gate:

    CLAIMTRACE_ALLOW_GPU=1 .venv/bin/python -m eval.run \
        --scorer local --path runs/xenc-a --save runs/xenc-a.json
    .venv/bin/python -m eval.run --compare runs/baseline-off-the-shelf.json runs/xenc-a.json
"""
import argparse
import json
import os
import sys

from .data import load_rows, split_by_day, summary
from .loop import Config, train


def main(argv=None):
    ap = argparse.ArgumentParser(description="train the claim-equivalence cross-encoder")
    ap.add_argument("--base", default=Config.base)
    ap.add_argument("--lr", type=float, default=Config.lr)
    ap.add_argument("--epochs", type=int, default=Config.epochs)
    ap.add_argument("--batch-size", type=int, default=Config.batch_size)
    ap.add_argument("--grad-accum", type=int, default=Config.grad_accum)
    ap.add_argument("--max-length", type=int, default=Config.max_length)
    ap.add_argument("--binary-loss-weight", type=float, default=Config.binary_loss_weight)
    ap.add_argument("--ce-loss-weight", type=float, default=Config.ce_loss_weight)
    ap.add_argument("--label-smoothing", type=float, default=Config.label_smoothing)
    ap.add_argument("--dropout", type=float, default=None)
    ap.add_argument("--weight-decay", type=float, default=Config.weight_decay)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-share", type=float, default=0.15)
    ap.add_argument("--out", default="runs/xenc")
    ap.add_argument("--all-languages", action="store_true",
                    help="include cross-lingual rows; English-only by default")
    ap.add_argument("--limit", type=int, default=None, help="truncate for a smoke test")
    ap.add_argument("--describe", action="store_true", help="print the data and exit")
    args = ap.parse_args(argv)

    rows = load_rows(english_only=not args.all_languages)
    if not rows:
        sys.exit("no training rows found; run the mine pipeline first")
    tr, va, rep = split_by_day(rows, val_share=args.val_share, seed=args.seed)
    print(summary(rows))
    print()
    for k, v in rep.items():
        print(f"  {k}: {v}")
    if args.describe:
        return 0
    if args.limit:
        # Shuffle before truncating. Taking the head gives a distorted class mix,
        # which made a smoke test report class weights pinned at the 8.0 cap.
        import random
        rng = random.Random(args.seed)
        tr, va = list(tr), list(va)
        rng.shuffle(tr)
        rng.shuffle(va)
        tr, va = tr[:args.limit], va[:max(64, args.limit // 8)]
        print(f"\n  SMOKE TEST: sampled {len(tr)} train / {len(va)} val")

    cfg = Config(base=args.base, lr=args.lr, epochs=args.epochs,
                 batch_size=args.batch_size, grad_accum=args.grad_accum,
                 max_length=args.max_length,
                 binary_loss_weight=args.binary_loss_weight,
                 ce_loss_weight=args.ce_loss_weight,
                 label_smoothing=args.label_smoothing, dropout=args.dropout,
                 weight_decay=args.weight_decay, seed=args.seed, out=args.out)
    print()
    result = train(cfg, tr, va)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out.rstrip("/") + ".train.json", "w") as fh:
        json.dump({**result, "data": rep}, fh, indent=2, default=str)
    best = result["best"]
    print(f"\n  best epoch {best['epoch']}: selection {best['selection']:.4f}, "
          f"robust margin {best['robust']:+.4f}, raw margin {best['margin']:+.4f}")
    print(f"  checkpoint {args.out}")
    print(f"  next: CLAIMTRACE_ALLOW_GPU=1 python -m eval.run --scorer local "
          f"--path {args.out} --save {args.out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
