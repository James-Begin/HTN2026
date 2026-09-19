"""Collect author feeds into a local corpus. Free, keyless, no GPU.

Pages to a COMMON FLOOR DATE, not a common page count. That distinction is the whole
point: candidates only form inside the date range where outlets overlap, and outlets
file at wildly different rates. Reuters posts 135 a day and AFP 17, so a flat 15
pages each gave Reuters 11 days and AFP three months, and pairs could only form in
the 11-day intersection. Measured consequence: tripling the corpus raised candidates
by only 41%.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from .bluesky import Bluesky, save
from .outlets import OUTLETS, pages_for

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def main(argv=None):
    ap = argparse.ArgumentParser(description="mine Bluesky outlet feeds (free)")
    ap.add_argument("--days", type=int, default=45,
                    help="page every outlet back this many days (the common floor)")
    ap.add_argument("--pages", type=int, default=None,
                    help="fixed page cap per outlet; overrides the per-outlet budget")
    ap.add_argument("--out", default=os.path.join(OUT, "corpus.jsonl"))
    ap.add_argument("--append", action="store_true",
                    help="merge into an existing corpus instead of replacing it")
    args = ap.parse_args(argv)

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()
    budget = {h: args.pages or pages_for(h, args.days) for h, _, _, _ in OUTLETS}
    print(f"  floor {since}  ({args.days} days)  page budget {sum(budget.values())}")

    bs = Bluesky()
    allp, failed = [], []
    for handle, lang, script, _ in OUTLETS:
        try:
            got = list(bs.author_feed(handle, lang, pages=budget[handle], since=since))
        except RuntimeError as ex:
            failed.append((handle, str(ex)[:60]))
            print(f"  {handle:<24s} FAILED {str(ex)[:50]}")
            continue
        allp.extend(got)
        span = f"{got[-1].day}..{got[0].day}" if got else "-"
        reached = "floor" if got and got[-1].day <= since else "SHORT"
        print(f"  {handle:<24s} {lang} {script:<8s} {len(got):>5d} posts  {span}  {reached}")

    if args.append and os.path.exists(args.out):
        from .bluesky import load
        prior = load(args.out)
        seen = {p.uri for p in allp}
        allp.extend(p for p in prior if p.uri not in seen)
        print(f"  merged {len(prior)} prior posts")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n = save(allp, args.out)
    days = sorted({p.day for p in allp})
    print(f"\n  {n} posts across {len(days)} days -> {args.out}")
    print(f"  {bs.report()}")
    if failed:
        print(f"  {len(failed)} outlets failed: " + ", ".join(h for h, _ in failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
