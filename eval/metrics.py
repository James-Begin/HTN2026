"""Metrics for claim-equivalence. Stdlib only, because the set is 25 rows and a
numpy dependency would be the largest thing in the directory.

What is measured and why:

  separation margin   min(score over positives) - max(score over negatives).
                      Positive means SOME threshold classifies the whole set
                      correctly. This single number is the honest headline: it is
                      currently deeply negative, and no amount of threshold
                      tuning fixes a negative margin.

  ROC AUC / avg prec  threshold-free ranking quality. Reported because a model can
                      improve ranking well before any fixed threshold works, and
                      we want to see that progress rather than a flat fail.

  calibration         ECE and Brier. A same-claim score that feeds an abstention
                      decision has to mean something. 0.9 must be right ~90% of
                      the time or "we abstain below 0.5" is theatre.

  coverage curve      precision as a function of how much we accept. This is the
                      product question: at what coverage do we hold 100%
                      precision, because that is the fraction of candidates the
                      pipeline can judge without a human.
"""
from .dataset import LABELS, POSITIVE_LABELS, THRESHOLD


# --------------------------------------------------------------- ranking quality
def roc_auc(pos: list, neg: list):
    """Mann-Whitney U with tied ranks averaged. Ties matter here: an off-the-shelf
    reranker returns exactly 0.0000 for several unrelated pairs."""
    if not pos or not neg:
        return None
    rows = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda r: r[0])
    rank_sum, i, n = 0.0, 0, len(rows)
    while i < n:
        j = i
        while j < n and rows[j][0] == rows[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0          # 1-indexed, averaged across the tie
        rank_sum += avg_rank * sum(g for _, g in rows[i:j])
        i = j
    npos, nneg = len(pos), len(neg)
    u = rank_sum - npos * (npos + 1) / 2.0
    return u / (npos * nneg)


def average_precision(scored: list):
    """scored = [(score, gold01)]. Precision at each positive, averaged."""
    rows = sorted(scored, key=lambda r: -r[0])
    npos = sum(g for _, g in rows)
    if not npos:
        return None
    tp, acc = 0, 0.0
    for rank, (_, gold) in enumerate(rows, 1):
        if gold:
            tp += 1
            acc += tp / rank
    return acc / npos


def separation(pos: list, neg: list):
    """(margin, worst_positive, best_negative). Positive margin = separable."""
    if not pos or not neg:
        return None, None, None
    return min(pos) - max(neg), min(pos), max(neg)


def robust_separation(pos: list, neg: list, q: float = 0.05):
    """Separation at the 5th/95th percentile instead of the min/max.

    Plain separation is a min-max statistic, so ONE outlier sets it. That is the right
    behaviour on the hand-labelled gate, where 25 pairs are all trusted and a single
    failure genuinely matters. It is the wrong behaviour on a 1,000-row
    machine-labelled validation split carrying roughly 6% label noise, where the
    single worst positive is usually just a mislabelled row.

    Measured: a checkpoint scoring ROC AUC 0.987 on validation reported a margin of
    -0.95, WORSE than the untrained baseline, purely because two rows out of 1,008 sat
    on the wrong side. Selecting on that number would have rejected a good model.
    """
    if not pos or not neg:
        return None
    p = sorted(pos)
    n = sorted(neg)
    lo = p[min(len(p) - 1, int(len(p) * q))]
    hi = n[max(0, int(len(n) * (1 - q)) - 1)]
    return lo - hi


# ------------------------------------------------------------------ thresholded
def confusion_at(scored: list, threshold: float = THRESHOLD) -> dict:
    tp = sum(1 for s, g in scored if g and s >= threshold)
    fp = sum(1 for s, g in scored if not g and s >= threshold)
    fn = sum(1 for s, g in scored if g and s < threshold)
    tn = sum(1 for s, g in scored if not g and s < threshold)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if prec is not None or rec is not None else None)
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec, "f1": f1,
            "accuracy": (tp + tn) / len(scored) if scored else None}


def best_threshold(scored: list):
    """The threshold maximising F1, and its confusion. Reported alongside the fixed
    0.5 so a run can show 'the ordering is fine, the scale is wrong'."""
    cands = sorted({s for s, _ in scored} | {0.0, 1.0})
    best = None
    for t in cands:
        c = confusion_at(scored, t)
        if c["f1"] is not None and (best is None or c["f1"] > best["f1"]):
            best = c
    return best


def coverage_curve(scored: list, steps: int = 21) -> list:
    """Sweep the threshold. Returns [{threshold, coverage, precision, recall}].

    Coverage is the share of the whole set we accept. The row to look for is the
    highest coverage at precision 1.0.
    """
    out = []
    for i in range(steps):
        t = i / (steps - 1)
        c = confusion_at(scored, t)
        accepted = c["tp"] + c["fp"]
        out.append({"threshold": round(t, 3),
                    "coverage": accepted / len(scored) if scored else 0.0,
                    "precision": c["precision"], "recall": c["recall"]})
    return out


def max_coverage_at_perfect_precision(scored: list):
    """The product number: how much can we auto-judge with zero false accepts."""
    best = 0.0
    thr = None
    for row in coverage_curve(scored, steps=101):
        if row["precision"] == 1.0 and row["coverage"] > best:
            best, thr = row["coverage"], row["threshold"]
    return best, thr


# ----------------------------------------------------------------- calibration
def brier(scored: list):
    return sum((s - g) ** 2 for s, g in scored) / len(scored) if scored else None


def calibration(scored: list, bins: int = 10):
    """Expected calibration error plus the reliability rows behind it.

    With 25 pairs the bins are sparse and ECE is noisy. It is here because it is
    the metric the hyperparameter sweep should optimise once the set is 300+ pairs,
    and wiring it in now means the sweep has a target on day one.
    """
    if not scored:
        return None, []
    rows, err, n = [], 0.0, len(scored)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(s, g) for s, g in scored
               if (lo <= s < hi) or (b == bins - 1 and s == 1.0)]
        if not sel:
            rows.append({"lo": lo, "hi": hi, "n": 0, "confidence": None, "accuracy": None})
            continue
        conf = sum(s for s, _ in sel) / len(sel)
        acc = sum(g for _, g in sel) / len(sel)
        err += len(sel) / n * abs(conf - acc)
        rows.append({"lo": lo, "hi": hi, "n": len(sel),
                     "confidence": conf, "accuracy": acc})
    return err, rows


# ------------------------------------------------------------------ per-class
def per_class(preds: list, threshold: float = THRESHOLD) -> dict:
    """preds = [(Pair, score, probs_or_None)]. Score distribution per gold label.

    This is the table that localises a failure. A single F1 says the model is bad;
    this says same_paraphrase averages 0.15 while meta averages 0.41, which names
    the actual defect.

    `threshold` must be threaded through from the caller. It used to be silently
    hardcoded to the module default: `evaluate(preds, threshold=0.70)` computed
    `at_threshold` at 0.70 correctly but this table's `n_wrong_side` stayed pinned to
    0.5, so the same report could show a case as an accept in one table and "wrong
    side of 0.5" in another. Caught while calibrating a new threshold and re-running
    the report at 0.70 instead of the default.
    """
    out = {}
    for label in LABELS:
        vals = sorted(s for p, s, _ in preds if p.label == label)
        if not vals:
            continue
        wants_high = label in POSITIVE_LABELS
        wrong = [v for v in vals
                 if (v < threshold if wants_high else v >= threshold)]
        out[label] = {
            "n": len(vals), "mean": sum(vals) / len(vals),
            "min": vals[0], "max": vals[-1], "median": vals[len(vals) // 2],
            "want": "high" if wants_high else "low",
            "n_wrong_side": len(wrong),
        }
    return out


def class_confusion(preds: list):
    """5x5 confusion, only for scorers that return a full distribution."""
    have = [(p, pr) for p, _, pr in preds if pr]
    if not have:
        return None
    mat = {g: {p: 0 for p in LABELS} for g in LABELS}
    for pair, probs in have:
        pred = max(LABELS, key=lambda l: probs.get(l, 0.0))
        mat[pair.label][pred] += 1
    return mat


# --------------------------------------------------------------------- rollup
def evaluate(preds: list, threshold: float = THRESHOLD) -> dict:
    """preds = [(Pair, score, probs_or_None)] for every pair that was scored."""
    scored = [(s, 1 if p.gold_positive else 0) for p, s, _ in preds]
    gating = [(s, 1 if p.gold_positive else 0) for p, s, _ in preds if p.gates]
    pos = [s for s, g in scored if g]
    neg = [s for s, g in scored if not g]
    margin, worst_pos, best_neg = separation(pos, neg)
    robust = robust_separation(pos, neg)
    ece, reliability = calibration(scored)
    cov, cov_thr = max_coverage_at_perfect_precision(scored)
    return {
        "n": len(preds),
        "n_gating": len(gating),
        "at_threshold": confusion_at(scored, threshold),
        "at_threshold_gating_only": confusion_at(gating, threshold) if gating else None,
        "best_threshold": best_threshold(scored),
        "roc_auc": roc_auc(pos, neg),
        "average_precision": average_precision(scored),
        "separation_margin": margin,
        "robust_separation_p5": robust,
        "worst_positive": worst_pos,
        "best_negative": best_neg,
        "brier": brier(scored),
        "ece": ece,
        "reliability": reliability,
        "coverage_curve": coverage_curve(scored),
        "max_coverage_at_perfect_precision": cov,
        "perfect_precision_threshold": cov_thr,
        "per_class": per_class(preds, threshold),
        "class_confusion": class_confusion(preds),
    }
