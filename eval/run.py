"""Run the eval and print a report.

    python -m eval.run                              # replay the recorded baseline, free
    python -m eval.run --scorer baseten             # the deployed cross-encoder
    CLAIMTRACE_ALLOW_GPU=1 python -m eval.run \
        --scorer local --path runs/xenc-5way        # a local checkpoint
    python -m eval.run --save runs/baseline.json
    python -m eval.run --compare runs/baseline.json runs/candidate.json

Nothing here trains, and nothing touches a GPU unless --scorer local is asked for
AND CLAIMTRACE_ALLOW_GPU=1 is set.
"""
import argparse
import json
import os
import sys
import time

from . import gates as G
from . import metrics as M
from .dataset import DEFAULT_PAIRS, LABELS, THRESHOLD, by_reference, load, summary
from .scorers import build

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"


def _c(colour, text, on=True):
    return f"{colour}{text}{RESET}" if on else str(text)


def _n(v, places=4):
    return "  n/a " if v is None else f"{v:.{places}f}"


# --------------------------------------------------------------------- scoring
def collect(scorer, pairs, threshold=THRESHOLD):
    """Score every pair, grouped by reference so each group is one request."""
    preds, skipped = [], []
    for reference, group in by_reference(pairs).items():
        results = scorer.score(reference, group)
        for pair, (score, probs) in zip(group, results):
            if score is None:
                skipped.append(pair)
            else:
                preds.append((pair, float(score), probs))
    return preds, skipped


# ---------------------------------------------------------------------- render
def render(preds, skipped, report, gate, scorer_name, wall, threshold=THRESHOLD, colour=True):
    """`threshold` must be the SAME value passed to `M.evaluate`/`G.check` upstream.

    Every number here used to display correctly at a custom --threshold except three
    things that stayed pinned to the module default of 0.5: this table's pass/fail
    mark, the PER CLASS "wrong side of" label, and the METRICS section's printed
    labels. `report["at_threshold"]` was already computed at the right value, so the
    *numbers* were correct and only the *labels and the per-case marks* lied about
    which threshold produced them. Caught re-running this report at 0.70 instead of
    the default while calibrating a new checkpoint's accept/reject cutoffs.
    """
    p = print

    p()
    p(_c(BOLD, f"CLAIM EQUIVALENCE EVAL   scorer={scorer_name}   "
                f"{len(preds)} scored, {len(skipped)} skipped, {wall:.1f}s", colour))

    # ---- per-case table, the part that localises a failure
    p()
    p(_c(BOLD, "  PER CASE", colour))
    p(_c(DIM, f"  {'id':<9s} {'gold':<16s} {'score':>7s} {'was':>7s} {'Δ':>7s}  verdict", colour))
    for pair, score, _ in sorted(preds, key=lambda r: (r[0].group, r[0].id)):
        want_high = pair.gold_positive
        ok = (score >= threshold) if want_high else (score < threshold)
        delta = None if pair.baseline is None else score - pair.baseline
        mark = _c(GREEN, "ok  ", colour) if ok else _c(RED, "FAIL", colour)
        if not pair.gates:
            mark = _c(YELLOW, "dbt ", colour)
        arrow = ""
        if delta is not None and abs(delta) >= 0.005:
            arrow = _c(GREEN if (delta > 0) == want_high else RED,
                       "↑" if delta > 0 else "↓", colour)
        p(f"  {pair.id:<9s} {pair.label:<16s} {score:>7.4f} "
          f"{_n(pair.baseline):>7s} {_n(delta, 3):>7s}{arrow} {mark} "
          f"{_c(DIM, pair.note[:52], colour)}")
    for pair in skipped:
        p(f"  {pair.id:<9s} {pair.label:<16s} {_c(DIM, 'not scored', colour)}")

    # ---- per class
    p()
    p(_c(BOLD, "  PER CLASS", colour))
    p(_c(DIM, f"  {'label':<16s} {'n':>3s} {'want':>5s} {'mean':>7s} "
              f"{'min':>7s} {'max':>7s}  wrong side of {threshold}", colour))
    for label in LABELS:
        row = report["per_class"].get(label)
        if not row:
            continue
        bad = row["n_wrong_side"]
        flag = _c(RED, f"{bad}/{row['n']}", colour) if bad else _c(GREEN, "0", colour)
        p(f"  {label:<16s} {row['n']:>3d} {row['want']:>5s} {row['mean']:>7.4f} "
          f"{row['min']:>7.4f} {row['max']:>7.4f}  {flag}")

    # ---- headline metrics
    at = report["at_threshold"]
    best = report["best_threshold"]
    p()
    p(_c(BOLD, "  METRICS", colour))
    sep = report["separation_margin"]
    sep_col = GREEN if (sep or -1) > 0 else RED
    sep_detail = ("worst positive " + _n(report["worst_positive"])
                  + ", best negative " + _n(report["best_negative"]))
    p("  separation margin      " + _c(sep_col, _n(sep), colour)
      + "   " + _c(DIM, sep_detail, colour))
    p("  ROC AUC                " + _n(report["roc_auc"])
      + "   " + _c(DIM, "ranking, scale-free", colour))
    p("  average precision      " + _n(report["average_precision"]))
    p("  Brier                  " + _n(report["brier"])
      + "   " + _c(DIM, "lower is better", colour))
    p("  ECE                    " + _n(report["ece"])
      + "   " + _c(DIM, "noisy below ~300 pairs", colour))
    counts = "tp {tp} fp {fp} fn {fn} tn {tn}".format(**at)
    p(f"  precision @ {threshold}        " + _n(at["precision"])
      + "   " + _c(DIM, counts, colour))
    p(f"  recall @ {threshold}           " + _n(at["recall"]))
    p(f"  F1 @ {threshold}               " + _n(at["f1"]))
    if best:
        p("  best F1 (any threshold)" + _n(best["f1"]).rjust(8)
          + "   " + _c(DIM, f"at threshold {best['threshold']:.4f}", colour))
    cov = report["max_coverage_at_perfect_precision"]
    p(f"  coverage @ 100% prec   {cov:.1%}".ljust(40)
      + _c(DIM, "threshold " + _n(report["perfect_precision_threshold"], 2), colour))

    cm = report.get("class_confusion")
    if cm:
        p()
        p(_c(BOLD, "  CLASS CONFUSION  (rows gold, cols predicted)", colour))
        short = [l[:6] for l in LABELS]
        p(_c(DIM, "  " + " " * 16 + "".join(f"{s:>8s}" for s in short), colour))
        for gold in LABELS:
            if not any(cm[gold].values()):
                continue
            p(f"  {gold:<16s}" + "".join(
                f"{cm[gold][pred]:>8d}" if gold != pred
                else _c(GREEN, f"{cm[gold][pred]:>8d}", colour) for pred in LABELS))

    # ---- gates, the actual decision
    p()
    p(_c(BOLD, "  GATES", colour))
    for kind, title in (("unlock", "must clear the threshold (the point of the fine-tune)"),
                        ("regression", "must stay below (already works, do not break)"),
                        ("aggregate", "set-level, advisory until the set is larger")):
        p(f"  {_c(DIM, title, colour)}")
        for row in gate["rows"]:
            if row["kind"] != kind:
                continue
            if row["passed"] is None:
                mark = _c(DIM, "skip", colour)
            else:
                mark = _c(GREEN, "pass", colour) if row["passed"] else _c(RED, "FAIL", colour)
            got = "n/a" if row["score"] is None else f"{row['score']:.4f}"
            p(f"    {mark}  {row['id']:<34s} {got:>8s} want {row['want']:<8s} "
              f"{_c(DIM, row['why'][:44], colour)}")

    p()
    p(f"  unlock     {gate['unlock_passed']}/{gate['unlock_total']}")
    p(f"  regression {gate['regression_held']}/{gate['regression_total']} held")
    p(f"  aggregate  {gate['aggregate_passed']}/{gate['aggregate_total']}")
    verdict = (_c(BOLD + GREEN, "SHIPPABLE", colour) if gate["shippable"]
               else _c(BOLD + RED, "NOT SHIPPABLE", colour))
    p(f"  {verdict}   {_c(DIM, 'ship only when every unlock passes and no regression breaks', colour)}")
    p()


# --------------------------------------------------------------------- compare
def compare(path_a, path_b, colour=True):
    a, b = (json.load(open(p)) for p in (path_a, path_b))
    print()
    print(_c(BOLD, f"  {os.path.basename(path_a)}  ->  {os.path.basename(path_b)}", colour))
    print()
    sa = {r["id"]: r for r in a["cases"]}
    sb = {r["id"]: r for r in b["cases"]}
    print(_c(DIM, f"  {'id':<9s} {'gold':<16s} {'a':>7s} {'b':>7s} {'Δ':>8s}", colour))
    for cid in sorted(set(sa) | set(sb)):
        ra, rb = sa.get(cid), sb.get(cid)
        va = ra["score"] if ra else None
        vb = rb["score"] if rb else None
        d = None if (va is None or vb is None) else vb - va
        gold = (rb or ra)["label"]
        want_high = gold in ("same_verbatim", "same_paraphrase")
        col = ""
        if d is not None and abs(d) >= 0.005:
            col = GREEN if (d > 0) == want_high else RED
        line = f"  {cid:<9s} {gold:<16s} {_n(va):>7s} {_n(vb):>7s} {_n(d, 4):>8s}"
        print(_c(col, line, colour and bool(col)))
    print()
    for key in ("separation_margin", "roc_auc", "average_precision", "ece", "brier",
                "max_coverage_at_perfect_precision"):
        va, vb = a["report"].get(key), b["report"].get(key)
        d = None if (va is None or vb is None) else vb - va
        print(f"  {key:<36s} {_n(va):>8s} {_n(vb):>8s} {_n(d):>9s}")
    print()


# ------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="claim-equivalence eval")
    ap.add_argument("--scorer", default="replay", choices=["replay", "baseten", "local", "deployed"])
    ap.add_argument("--path", help="checkpoint directory, for --scorer local")
    ap.add_argument("--pairs", default=DEFAULT_PAIRS)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--save", metavar="FILE", help="write the full result as JSON")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--describe", action="store_true", help="print the set and exit")
    ap.add_argument("--english", action="store_true",
                    help="keep only pairs where both sides are English. Scoping the "
                         "eval to match the training scope; costs measurement power")
    ap.add_argument("--holdout", action="store_true",
                    help="score eval/holdout.jsonl instead: 180 blind-labelled pairs, "
                         "not gated per-pair, weighted toward the decision boundary")
    ap.add_argument("--no-colour", action="store_true")
    args = ap.parse_args(argv)
    colour = not args.no_colour and sys.stdout.isatty()

    if args.compare:
        compare(*args.compare, colour=colour)
        return 0

    if args.holdout:
        args.pairs = os.path.join(os.path.dirname(DEFAULT_PAIRS), "holdout.jsonl")
    pairs = load(args.pairs)
    if args.english:
        import json as _json
        prov = {}
        with open(args.pairs) as _fh:
            for _l in _fh:
                if _l.strip():
                    _r = _json.loads(_l)
                    prov[_r["id"]] = _r.get("source") or {}
        before = len(pairs)
        pairs = [p for p in pairs
                 if prov.get(p.id, {}).get("a_lang") in (None, "en")
                 and prov.get(p.id, {}).get("b_lang") in (None, "en")]
        print(f"  english-only: {len(pairs)} of {before} pairs "
              f"(pairs without provenance are kept; the 25 gate pairs have none)")
    if args.describe:
        print(summary(pairs))
        return 0

    kw = {}
    if args.scorer == "local":
        if not args.path:
            ap.error("--scorer local needs --path")
        kw["path"] = args.path
    scorer = build(args.scorer, pairs, **kw)

    t0 = time.time()
    preds, skipped = collect(scorer, pairs, args.threshold)
    wall = time.time() - t0
    if not preds:
        print("nothing was scored", file=sys.stderr)
        return 2

    report = M.evaluate(preds, args.threshold)
    gate = G.check(preds, report, args.threshold)
    render(preds, skipped, report, gate, scorer.name, wall, args.threshold, colour)
    print(_c(DIM, "  " + scorer.report(), colour))

    if args.save:
        os.makedirs(os.path.dirname(os.path.abspath(args.save)), exist_ok=True)
        with open(args.save, "w") as fh:
            json.dump({
                "scorer": scorer.name,
                "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "threshold": args.threshold,
                "wall_s": round(wall, 2),
                "cases": [{"id": p.id, "label": p.label, "confidence": p.confidence,
                           "score": s, "baseline": p.baseline, "probs": pr}
                          for p, s, pr in preds],
                "skipped": [p.id for p in skipped],
                "report": report,
                "gates": gate,
            }, fh, indent=2)
        print(_c(DIM, f"  saved {args.save}", colour))

    # Exit 0 always. This is a measurement, not a test: a failing gate today is
    # the expected state, and a non-zero exit would break any wrapper that runs it.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
