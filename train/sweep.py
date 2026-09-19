"""Parallel hyperparameter sweep, one configuration per GPU.

This is the thing the eight local A10Gs buy that Baseten's training product does not
offer at all: it has no sweep facility. A single config takes about twelve minutes, so
eight run in the same twelve minutes rather than ninety-six.

Each configuration is scored on the RELEASE GATE, not only on validation. Validation
is 1,100 machine-labelled rows with roughly 6% label noise; the gate is 25
hand-labelled pairs chosen because each one is a known failure. A config that improves
validation while breaking a regression gate is worse, and only the gate can say so.

Ranking is lexicographic and deliberately so:
  1. unlock gates passed        the point of the fine-tune
  2. regression gates held      not breaking what already worked
  3. robust separation          how cleanly the distributions split
A single scalar would let a config trade a broken regression for a prettier average.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")

# Axes chosen from what the first two runs actually showed, not from a grid:
#   * epoch 3 kept improving robust margin while AUC dipped, so epochs 2-4 matter
#   * the binary term is the trustworthy signal (94% vs 74% label agreement), so its
#     weight is the most promising single knob
#   * ssi-05 is the one failing gate, an acronym collision scoring 0.587, which argues
#     for stronger regularisation and a lower learning rate
EN_GRID = [
    # English-only makes the base-model question live again. bge-reranker-v2-m3 is 568M
    # with a 250k multilingual vocab; bge-reranker-base is 278M with a 30k English vocab
    # and would roughly halve the 6.6x serving cost. It lost badly in the first sweep
    # (2/4 unlock, AUC 0.818) but that sweep had cross-lingual data in play, where a
    # multilingual base wins by construction. It deserves a fair retest.
    dict(tag="en-m3",   lr=2e-5, epochs=3, binary_loss_weight=1.0, label_smoothing=0.05),
    dict(tag="en-base", lr=3e-5, epochs=4, binary_loss_weight=1.0, label_smoothing=0.05,
         base="BAAI/bge-reranker-base"),
]

GRID = [
    dict(tag="a-base",      lr=2e-5, epochs=3, binary_loss_weight=1.0, label_smoothing=0.05),
    dict(tag="b-lowlr",     lr=1e-5, epochs=4, binary_loss_weight=1.0, label_smoothing=0.05),
    dict(tag="c-binheavy",  lr=2e-5, epochs=3, binary_loss_weight=2.5, label_smoothing=0.05),
    dict(tag="d-binlight",  lr=2e-5, epochs=3, binary_loss_weight=0.3, label_smoothing=0.05),
    dict(tag="e-smooth",    lr=2e-5, epochs=3, binary_loss_weight=1.0, label_smoothing=0.15),
    dict(tag="f-nosmooth",  lr=2e-5, epochs=3, binary_loss_weight=1.0, label_smoothing=0.0),
    dict(tag="g-long",      lr=1e-5, epochs=5, binary_loss_weight=2.0, label_smoothing=0.1),
    dict(tag="h-smallbase", lr=3e-5, epochs=4, binary_loss_weight=1.0, label_smoothing=0.05,
         base="BAAI/bge-reranker-base"),
]


def run_one(idx: int, cfg: dict, gpu: int, outdir: str, extra: list) -> dict:
    tag = cfg["tag"]
    out = os.path.join(outdir, tag)
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(gpu),
               HF_HUB_DISABLE_PROGRESS_BARS="1", TOKENIZERS_PARALLELISM="false")
    args = [PY, "-m", "train.run", "--out", out]
    for k, v in cfg.items():
        if k == "tag":
            continue
        args += [f"--{k.replace('_', '-')}", str(v)]
    args += extra

    t0 = time.time()
    log_path = out + ".log"
    os.makedirs(outdir, exist_ok=True)
    with open(log_path, "w") as fh:
        train_rc = subprocess.run(args, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                  cwd=ROOT).returncode
    row = {"tag": tag, "gpu": gpu, "config": cfg, "out": out,
           "train_rc": train_rc, "secs": round(time.time() - t0)}
    if train_rc != 0:
        row["error"] = f"training failed, see {log_path}"
        return row

    # Score against the release gate.
    genv = dict(env, CLAIMTRACE_ALLOW_GPU="1")
    gate_json = out + ".json"
    with open(out + ".eval.log", "w") as fh:
        rc = subprocess.run(
            [PY, "-m", "eval.run", "--scorer", "local", "--path", out,
             "--no-colour", "--save", gate_json],
            env=genv, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT).returncode
    if rc != 0 or not os.path.exists(gate_json):
        row["error"] = f"eval failed, see {out}.eval.log"
        return row

    blob = json.load(open(gate_json))
    g, r = blob["gates"], blob["report"]
    row.update({
        "unlock": f"{g['unlock_passed']}/{g['unlock_total']}",
        "unlock_n": g["unlock_passed"],
        "regression": f"{g['regression_held']}/{g['regression_total']}",
        "regression_n": g["regression_held"],
        "shippable": g["shippable"],
        "roc_auc": r["roc_auc"], "margin": r["separation_margin"],
        "robust": r.get("robust_separation_p5"), "ece": r["ece"],
        "coverage": r["max_coverage_at_perfect_precision"],
        "failed_gates": [x["id"] for x in g["rows"]
                         if x["passed"] is False and x["kind"] != "aggregate"],
    })
    if os.path.exists(out + ".train.json"):
        tj = json.load(open(out + ".train.json"))
        row["val_auc"] = (tj.get("best") or {}).get("report", {}).get("roc_auc")
        row["best_epoch"] = (tj.get("best") or {}).get("epoch")
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="parallel sweep, one config per GPU")
    ap.add_argument("--gpus", default="0,1,2,3,4,5,6,7")
    ap.add_argument("--outdir", default="runs/sweep")
    ap.add_argument("--only", default="", help="comma-separated tags to run")
    ap.add_argument("--all-languages", action="store_true")
    ap.add_argument("--english-grid", action="store_true",
                    help="the 2-config base-model comparison for English-only")
    args = ap.parse_args(argv)

    gpus = [int(g) for g in args.gpus.split(",") if g.strip() != ""]
    grid = EN_GRID if args.english_grid else GRID
    if args.only:
        want = {t.strip() for t in args.only.split(",")}
        grid = [c for c in GRID if c["tag"] in want]
    extra = ["--all-languages"] if args.all_languages else []

    print(f"  {len(grid)} configs across {len(gpus)} GPUs -> {args.outdir}")
    for c in grid:
        print(f"    {c['tag']:<12s} " + " ".join(f"{k}={v}" for k, v in c.items() if k != "tag"))
    print()

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(gpus)) as pool:
        futures = [pool.submit(run_one, i, c, gpus[i % len(gpus)], args.outdir, extra)
                   for i, c in enumerate(grid)]
        rows = []
        for f in futures:
            row = f.result()
            rows.append(row)
            status = row.get("error") or (
                f"unlock {row['unlock']}  regression {row['regression']}  "
                f"auc {row['roc_auc']:.4f}  robust {row.get('robust') or 0:+.3f}")
            print(f"  done {row['tag']:<12s} {row['secs']:>4d}s  {status}")

    def key(r):
        return (r.get("unlock_n", -1), r.get("regression_n", -1),
                r.get("robust") if r.get("robust") is not None else -9,
                r.get("roc_auc") or 0)

    rows.sort(key=key, reverse=True)
    print(f"\n  swept in {(time.time() - t0) / 60:.1f} min\n")
    hdr = (f"  {'tag':<12s} {'unlock':>7s} {'regr':>6s} {'auc':>7s} {'robust':>7s} "
           f"{'ece':>6s} {'cov':>5s} {'ship':>5s}  failing")
    print(hdr)
    for r in rows:
        if r.get("error"):
            print(f"  {r['tag']:<12s} ERROR {r['error'][:60]}")
            continue
        print(f"  {r['tag']:<12s} {r['unlock']:>7s} {r['regression']:>6s} "
              f"{r['roc_auc']:>7.4f} {(r.get('robust') or 0):>+7.3f} {r['ece']:>6.3f} "
              f"{r['coverage']:>5.0%} {str(r['shippable']):>5s}  "
              + ",".join(r["failed_gates"]))

    with open(os.path.join(args.outdir, "sweep.json"), "w") as fh:
        json.dump(rows, fh, indent=2, default=str)
    best = next((r for r in rows if not r.get("error")), None)
    if best:
        print(f"\n  best: {best['tag']} -> {best['out']}")
        if best["shippable"]:
            print("  SHIPPABLE. Push this one to Baseten.")
        else:
            print(f"  not shippable yet; still failing: {','.join(best['failed_gates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
