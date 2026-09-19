"""Label more English event pairs with the hybrid labeller.

Scoping the project to English cut `same_paraphrase` from 6,263 rows to 1,364, because
most paraphrase pairs were cross-lingual: different-language outlets share only entity
names, so their pairs sit at low lexical overlap and read as paraphrases, while English
outlets share more wording and produce fewer distinct-wording pairs.

1,209 paraphrase rows against 3,287 incidental is a 2.7-to-1 negative ratio on the exact
discrimination that matters, so the class needs more data. Loosening the same-language
join from 3 shared rare tokens to 2 exposes 6,296 candidates that were never labelled.

Precision of the looser join is lower, so more of these will come back negative. That is
not waste: `incidental` lost 2,254 rows to `meta` in the re-label and its mean score
drifted up from 0.2733 to 0.4206, so hard negatives are wanted too.
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

from .bluesky import load as load_posts
from .label import RateLimiter, write_rows
from .label2 import label_hybrid
from .outlets import LANG_OF
from .pairs import build


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-shared", type=int, default=2)
    ap.add_argument("--limit", type=int, default=6500)
    ap.add_argument("--existing", default="mine/out/train-relabelled.jsonl")
    ap.add_argument("--out", default="mine/out/train-en-extra.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    have = set()
    if os.path.exists(args.existing):
        with open(args.existing) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    have.add((r["reference"], r["candidate"]))

    posts = [p for p in load_posts("mine/out/corpus.jsonl") if LANG_OF.get(p.handle) == "en"]
    cands = [c for c in build(posts, min_same=args.min_shared, min_cross=2)
             if (c.a_text, c.b_text) not in have][:args.limit]
    print(f"  {len(cands)} new English candidates at min_shared={args.min_shared}")
    print(f"  all are outlet-vs-outlet, so the meta question is skipped: ~{len(cands)} calls,"
          f" ~{len(cands) / 110:.0f} min")
    if args.dry_run or not cands:
        return 0

    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        sys.exit("BASETEN_API_KEY is not set")
    llm = HostedLLM(key)
    limiter, lock, done = RateLimiter(), threading.Lock(), [0]
    out = [None] * len(cands)
    t0 = time.time()

    def work(i):
        c = cands[i]
        limiter.acquire()
        src = {"b_handle": c.b_handle}
        out[i] = label_hybrid(llm, c.id, c.a_text, c.b_text, src)
        with lock:
            done[0] += 1
            if done[0] % 250 == 0 or done[0] == len(cands):
                print(f"\r  {done[0]}/{len(cands)}  {(time.time() - t0) / 60:.0f}m",
                      end="", flush=True)

    with ThreadPoolExecutor(max_workers=C.HOSTED_SAFE_CONCURRENCY) as pool:
        list(pool.map(work, range(len(cands))))
    print()

    rows = []
    for c, r in zip(cands, out):
        if not r or not r.ok:
            continue
        rows.append({
            "id": f"en2-{c.id}", "reference": c.a_text, "candidate": c.b_text,
            "label": r.label, "confidence": "machine", "note": r.reason,
            "source": {"kind": "bluesky-mined-en2", "a_uri": c.a_uri, "b_uri": c.b_uri,
                       "a_handle": c.a_handle, "b_handle": c.b_handle,
                       "a_lang": c.a_lang, "b_lang": c.b_lang,
                       "a_day": c.a_day, "b_day": c.b_day,
                       "shared": c.shared, "jaccard": c.jaccard,
                       "cross_lingual": c.cross_lingual,
                       "relabel": {"stage": r.stage}},
        })
    write_rows(rows, args.out)
    print(f"\n  {len(rows)} rows -> {args.out}")
    print("  labels: " + ", ".join(f"{k}={v}" for k, v in
                                   Counter(r["label"] for r in rows).most_common()))
    print(f"  {llm.report()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
