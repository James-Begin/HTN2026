"""Throughput and latency for the deployed cross-encoder.

The number that matters is pairs/second, because the pipeline's design argument is
that every candidate can be scored exhaustively rather than pre-filtered. The
off-the-shelf 1-logit reranker on Baseten's TensorRT engine measured 2,851 pairs/sec
on one L4. This is a 568M XLM-RoBERTa with a 5-class head on a plain PyTorch server,
so the comparison is the honest cost of the fine-tune.

Uses real post text, because latency scales with token count and synthetic short
strings would flatter the result.
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get("CLAIMTRACE_XENC_URL", "")
KEY = os.environ.get("BASETEN_API_KEY", "")


def call(query, texts, timeout=180):
    body = json.dumps({"query": query, "texts": texts,
                       "return_distribution": False}).encode()
    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": f"Api-Key {KEY}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read())
    return time.perf_counter() - t0, len(d.get("data", []))


def load_texts(n=400):
    """Real headlines, so token lengths are realistic."""
    rows = []
    path = "mine/out/train-all.jsonl"
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                if len(rows) >= n + 1:
                    break
                r = json.loads(line)
                if r.get("candidate"):
                    rows.append(r["candidate"])
    while len(rows) < n + 1:
        rows.append("A placeholder claim about an event that happened yesterday somewhere")
    return rows[0], rows[1:n + 1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=8, help="requests per concurrency level")
    args = ap.parse_args(argv)
    if not URL or not KEY:
        sys.exit("set CLAIMTRACE_XENC_URL and BASETEN_API_KEY")

    query, texts = load_texts(400)
    lens = [len(t) for t in texts]
    print(f"  real candidate text: median {statistics.median(lens):.0f} chars, "
          f"p90 {sorted(lens)[int(len(lens) * 0.9)]:.0f}")

    print("\n  warming the replica")
    for _ in range(3):
        call(query, texts[:32])

    print(f"\n  {'batch':>6s} {'reqs':>5s} {'p50 ms':>8s} {'p95 ms':>8s} {'pairs/s':>9s}")
    for bs in (1, 8, 32, 64):
        lat = []
        for i in range(args.batches):
            dt, n = call(query, texts[i * bs:(i * bs) + bs] or texts[:bs])
            lat.append(dt)
        p50 = statistics.median(lat)
        p95 = sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]
        print(f"  {bs:>6d} {len(lat):>5d} {p50 * 1000:>8.0f} {p95 * 1000:>8.0f} "
              f"{bs / p50:>9.1f}")

    print(f"\n  {'conc':>5s} {'batch':>6s} {'pairs':>6s} {'wall s':>7s} {'pairs/s':>9s}")
    for conc in (1, 4, 8, 16):
        bs = 32
        n_req = max(conc * 3, 8)
        work = [texts[(i * bs) % max(1, len(texts) - bs):][:bs] for i in range(n_req)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=conc) as pool:
            got = list(pool.map(lambda t: call(query, t), work))
        wall = time.perf_counter() - t0
        pairs = sum(n for _, n in got)
        print(f"  {conc:>5d} {bs:>6d} {pairs:>6d} {wall:>7.2f} {pairs / wall:>9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
