"""Release gates. The explicit answer to "is this checkpoint better than what we
already serve, and is it safe to push?"

Two kinds of gate, and the distinction is the point:

  UNLOCK gates    the paraphrase failures that motivated the fine-tune at all.
                  These are currently failing. Passing them is the whole project.

  REGRESSION gates the collisions the off-the-shelf model already handles. A
                  fine-tune that fixes paraphrase recall by scoring everything
                  high has not helped, it has moved the failure. These pass today
                  and must keep passing.

A checkpoint ships only when every UNLOCK gate passes and no REGRESSION gate
breaks. Reported per gate, never as a single pass/fail, because "8 of 9" tells you
which direction to go and "FAIL" does not.
"""
from .dataset import THRESHOLD

# Individual pairs that must clear the accept threshold. Each is a measured
# failure of the served model, with the number it currently produces.
# OUT OF SCOPE while the project is English-only. Kept as data, not gated:
#   ptf-03  Arabic restatement of the same announcement. It was the worst measured
#           failure at 0.012 and reached 0.8685 with cross-lingual training, then fell
#           to 0.4519 when the training set was re-labelled. Gating on it while training
#           English-only is what produced an unresolvable threshold earlier: the model
#           separated English cleanly and cross-lingual not at all, so it wanted two
#           different cutoffs and could serve one.
OUT_OF_SCOPE = {"ptf-03": "cross-lingual; project scoped to English"}

UNLOCK_PAIRS = {
    "ssi-03": "English paraphrase, no shared phrase (was 0.288)",
    "ptf-02": "the title plus a link to the same essay (was 0.261)",
    "dril-01": "a repost with the original's typo corrected",
}

# Individual pairs that must stay BELOW the accept threshold.
REGRESSION_PAIRS = {
    "ssi-04": "Korean honorific '-ssi' (holds at 0.034)",
    "ssi-05": "Supplemental Security Income, 2017",
    "ssi-06": "shares the entity OpenAI and nothing else (holds at 0.000)",
    "ssi-07": "spam matching on one word (holds at 0.000)",
    "ssi-10": "a reply DISPUTING the claim; must never count as corroboration",
    "ptf-05": "commentary about reactions, currently a false accept at 0.813",
    "cov-02": "the live follow-up six hours after the deleted original",
}

# Set-level thresholds.
AGGREGATE_GATES = [
    ("separation_margin", "gt", 0.0,
     "some threshold separates the whole set; negative means none does"),
    ("roc_auc", "gte", 0.95, "ranking quality independent of scale"),
    ("average_precision", "gte", 0.90, "ranking quality weighted toward the top"),
    ("ece", "lte", 0.10, "a 0.9 score must be right about 90% of the time"),
    ("max_coverage_at_perfect_precision", "gte", 0.80,
     "share of candidates judgeable with zero false accepts"),
]

_OPS = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}
_SYM = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def check(preds: list, report: dict, threshold: float = THRESHOLD) -> dict:
    """preds = [(Pair, score, probs)]. Returns per-gate results plus a rollup."""
    scores = {p.id: s for p, s, _ in preds}
    rows = []

    for pid, why in UNLOCK_PAIRS.items():
        s = scores.get(pid)
        rows.append({"kind": "unlock", "id": pid, "why": why, "score": s,
                     "want": f">= {threshold}",
                     "passed": None if s is None else s >= threshold})

    for pid, why in REGRESSION_PAIRS.items():
        s = scores.get(pid)
        rows.append({"kind": "regression", "id": pid, "why": why, "score": s,
                     "want": f"< {threshold}",
                     "passed": None if s is None else s < threshold})

    for key, op, bound, why in AGGREGATE_GATES:
        v = report.get(key)
        rows.append({"kind": "aggregate", "id": key, "why": why, "score": v,
                     "want": f"{_SYM[op]} {bound}",
                     "passed": None if v is None else _OPS[op](v, bound)})

    scored = [r for r in rows if r["passed"] is not None]
    unlock = [r for r in scored if r["kind"] == "unlock"]
    regress = [r for r in scored if r["kind"] == "regression"]
    agg = [r for r in scored if r["kind"] == "aggregate"]
    return {
        "rows": rows,
        "skipped": [r["id"] for r in rows if r["passed"] is None],
        "unlock_passed": sum(r["passed"] for r in unlock),
        "unlock_total": len(unlock),
        "regression_held": sum(r["passed"] for r in regress),
        "regression_total": len(regress),
        "aggregate_passed": sum(r["passed"] for r in agg),
        "aggregate_total": len(agg),
        # Shipping requires the unlocks AND no regression. Aggregates are advisory
        # until the set is large enough for ECE to mean anything.
        "shippable": bool(unlock) and all(r["passed"] for r in unlock + regress),
    }
