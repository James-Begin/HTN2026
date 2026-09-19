"""Incremental re-label of the training set with the hybrid labeller.

Full re-labelling would be ~21,000 calls. It is not needed, because the hybrid differs
from the 5-way prompt in exactly two situations:

  1. B is a reply and the meta detector fires  -> becomes `meta`
  2. the existing label is `meta` but the detector did not fire, or B is a newsroom
     where `meta` is 1-in-157  -> reassigned by the same-claim question

Every other row keeps its existing label, because on those the hybrid IS the 5-way
prompt. So only the reply rows need the meta question, plus the small set of rows
currently labelled `meta` that the evidence contradicts. That is roughly 8,700 calls
instead of 21,000.

Structural rows are never touched. Their labels come from construction, and
`same_verbatim` measured 100% and the random negatives are correct by guard.
"""
import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from claimtrace import config as C
from claimtrace.baseten import HostedLLM

from .label import RateLimiter
from .label2 import META_SYSTEM, SAME_SYSTEM, _ask, _is_verbatim, b_is_outlet
from .text import tokens


def plan(rows):
    """Split rows into: needs the meta question, needs reassignment, or untouched."""
    need_meta, need_same, keep = [], [], []
    for r in rows:
        if r.get("confidence") != "machine":
            keep.append(r)
            continue
        src = r.get("source") or {}
        if not b_is_outlet(src):
            need_meta.append(r)
        elif r["label"] == "meta":
            need_same.append(r)
        else:
            keep.append(r)
    return need_meta, need_same, keep


def main(argv=None):
    ap = argparse.ArgumentParser(description="re-label with the hybrid labeller")
    ap.add_argument("--in", dest="src", default="mine/out/train-all.jsonl")
    ap.add_argument("--out", default="mine/out/train-relabelled.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    rows = [json.loads(l) for l in open(args.src) if l.strip()]
    need_meta, need_same, keep = plan(rows)
    if args.limit:
        need_meta = need_meta[:args.limit]
    print(f"  {len(rows)} rows total")
    print(f"    {len(need_meta):>6d} reply rows -> ask the meta question")
    print(f"    {len(need_same):>6d} rows labelled meta that the prior contradicts")
    print(f"    {len(keep):>6d} untouched (structural, or 5-way is already the hybrid)")
    est = len(need_meta) + len(need_same)
    print(f"    ~{est} calls, ~{est / 110:.0f} min at the 110/min cap")
    if args.dry_run:
        return 0

    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        sys.exit("BASETEN_API_KEY is not set")
    llm = HostedLLM(key)
    limiter, lock, done = RateLimiter(), threading.Lock(), [0]
    total = len(need_meta) + len(need_same)
    changed = Counter()
    t0 = time.time()

    def tick():
        with lock:
            done[0] += 1
            if done[0] % 200 == 0 or done[0] == total:
                el = time.time() - t0
                print(f"\r  {done[0]}/{total}  {el / 60:.0f}m", end="", flush=True)

    def do_meta(r):
        limiter.acquire()
        got = _ask(llm, META_SYSTEM, r["reference"], r["candidate"], "response")
        tick()
        if got and got[0]:
            if r["label"] != "meta":
                changed[f'{r["label"]}->meta'] += 1
            r["source"]["relabel"] = {"stage": "meta-detector",
                                      "was": r["label"], "confidence": got[1]}
            r["label"] = "meta"
            r["note"] = got[2] or r.get("note", "")
        elif r["label"] == "meta":
            need_same.append(r)          # detector disagrees; resolve below
        return r

    def do_same(r):
        limiter.acquire()
        got = _ask(llm, SAME_SYSTEM, r["reference"], r["candidate"], "same")
        tick()
        if got is None:
            return r
        if got[0]:
            lab = "same_verbatim" if _is_verbatim(r["reference"], r["candidate"]) \
                else "same_paraphrase"
        else:
            shared = tokens(r["reference"]) & tokens(r["candidate"])
            lab = "incidental" if len(shared) >= 2 else "unrelated"
        if lab != r["label"]:
            changed[f'{r["label"]}->{lab}'] += 1
        r["source"]["relabel"] = {"stage": "meta-overruled", "was": r["label"],
                                  "confidence": got[1]}
        r["label"] = lab
        return r

    with ThreadPoolExecutor(max_workers=C.HOSTED_SAFE_CONCURRENCY) as pool:
        need_meta = list(pool.map(do_meta, need_meta))
    total = len(need_meta) + len(need_same)
    with ThreadPoolExecutor(max_workers=C.HOSTED_SAFE_CONCURRENCY) as pool:
        need_same = list(pool.map(do_same, need_same))
    print()

    out = keep + need_meta + [r for r in need_same]
    seen, final = set(), []
    for r in out:
        k = (r["reference"], r["candidate"])
        if k in seen:
            continue
        seen.add(k)
        final.append(r)
    with open(args.out, "w") as fh:
        for r in final:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    before = Counter(json.loads(l)["label"] for l in open(args.src) if l.strip())
    after = Counter(r["label"] for r in final)
    print(f"\n  {len(final)} rows -> {args.out}")
    print(f"  {'class':<16s} {'before':>7s} {'after':>7s} {'delta':>7s}")
    for c in sorted(set(before) | set(after)):
        print(f"  {c:<16s} {before.get(c, 0):>7d} {after.get(c, 0):>7d} "
              f"{after.get(c, 0) - before.get(c, 0):>+7d}")
    print("\n  label changes:")
    for k, v in changed.most_common(12):
        print(f"    {k:<34s} {v}")
    print(f"\n  {llm.report()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
