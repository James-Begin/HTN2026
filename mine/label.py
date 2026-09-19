"""Label candidate pairs into the five classes using a hosted model.

The design rule: the model LABELS REAL TEXT, it never WRITES text. Real text keeps
the distribution honest, and the only error introduced is label noise, which is
measurable. Generation would introduce distribution error, which is not.

Whether the labels can be trusted is an empirical question with an available
answer, so it is answered rather than assumed. `validate()` runs the labeller over
`eval/pairs.jsonl`, which is hand-labelled, and reports agreement. If the labeller
cannot reproduce hand labels it does not get to make new ones.
"""
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from claimtrace.baseten import HostedLLM
from claimtrace import config as C

from .pairs import Candidate

LABEL_SYSTEM = """You compare two social posts and decide how their CLAIMS relate.

Reply with JSON only: {"label": str, "confidence": float, "reason": str}

`reason` is at most 12 words. `confidence` is 0-1.

The five labels, in the order you should consider them:

"same_verbatim" - the same claim in substantially the same words. Reposts, copied
  text, wire copy republished, one text being a truncation of the other.

"same_paraphrase" - the same claim, different words. THIS INCLUDES DIFFERENT
  LANGUAGES, and it includes cases where each text emphasises different details of
  one event. Two reports of one announcement are same_paraphrase even if one
  mentions a venue the other omits. Ask: would a reader learn the same fact?

"meta" - ABOUT the claim rather than an instance of it. Commentary, endorsement,
  DISPUTE OR DENIAL, a question about its source, a joke built on it, or reporting
  on reactions to it. A post denying a claim is meta, never same. This matters:
  treating a denial as agreement inverts the conclusion.

"incidental" - shares names, numbers or topic, but asserts a DIFFERENT thing. This
  is the most common trap. Examples that are incidental, not same:
    - a preview of a match vs the result of that match
    - two separate events in one ongoing conflict on the same day
    - a person appearing in two unrelated stories
    - an acronym or name that means something else entirely
  Same subject is NOT the same claim. Be strict here.

"unrelated" - no meaningful connection; the overlap is coincidence.

Decide on the CLAIM, not the topic. When torn between same_paraphrase and
incidental, ask whether both texts assert the SAME fact about the SAME occurrence.
If either asserts something the other does not, prefer incidental.

Four boundary rules. These resolve the cases that are otherwise judged
inconsistently, so apply them literally:

1. COMPARE AGAINST WHAT A ACTUALLY ASSERTS, not against what A is about. A post
   announcing an essay asserts the ANNOUNCEMENT. Someone agreeing with that essay's
   argument is NOT restating the announcement, so that is "meta". A post reporting
   a study asserts the finding; someone arguing the same position independently is
   "meta", not "same_paraphrase".

2. "same_verbatim" covers identical text, one text being a truncation of the other,
   and text differing ONLY in spelling, punctuation, capitalisation, emoji or a
   corrected typo. Any genuine rewording is "same_paraphrase" instead.

3. "incidental" when the two share a proper noun, a number, a place or a named
   entity but assert different things. Reserve "unrelated" for when the only
   overlap is ordinary vocabulary or pure coincidence. If you can name a shared
   entity, it is incidental rather than unrelated.

4. A post that merely NAMES a claim without asserting it, such as a bare headline
   plus a link, or a title quoted as a punchline, carries the claim forward. If the
   naming reproduces the claim's own words, that is "same_verbatim". If it comments
   on the claim, that is "meta".

5. Any post that DENIES, disputes, corrects, debunks or fact-checks the claim is
   "meta". It is never "incidental" and never "same", however much wording it
   shares. A denial is a response to the claim, which is what "meta" means.

6. AN ACRONYM OR NAME THAT REFERS TO A DIFFERENT THING IS "incidental", no matter
   how similar the surrounding words look. Check that the entities are the same
   entities before deciding two claims match. Identical wording about different
   referents is the single most common error to avoid: "SSI" as a company and "SSI"
   as a government benefit are unrelated referents, so posts about each being
   delayed are "incidental" and definitely not "same_paraphrase"."""

LABELS_VALID = {"same_verbatim", "same_paraphrase", "meta", "incidental", "unrelated"}

# Three buckets, for measuring agreement on decisions that actually matter.
#
# `incidental` and `unrelated` are folded together because nothing downstream
# distinguishes them: both are negatives, both must score low, and no gate keys on
# the difference. They stay separate as LABELS because incidental is the hard
# negative and training should be able to weight it, but disagreeing about which
# kind of negative something is costs nothing, so it should not count as an error.
#
# `meta` stays its own bucket. Confusing it with a positive inverts a verify run's
# conclusion, which is the single most expensive mistake this model can make.
BUCKETS = {"same_verbatim": "same", "same_paraphrase": "same",
           "meta": "meta", "incidental": "not_same", "unrelated": "not_same"}


def collapse(label: str) -> str:
    return BUCKETS.get(label, label)


@dataclass
class Labelled:
    id: str
    label: str
    confidence: float
    reason: str
    ok: bool = True
    error: str = ""


def _prompt(a: str, b: str) -> str:
    return f"POST A:\n{a[:600]}\n\nPOST B:\n{b[:600]}"


_SALVAGE_LABEL = re.compile(r'"label"\s*:\s*"([a-z_]+)"')
_SALVAGE_CONF = re.compile(r'"confidence"\s*:\s*([0-9.]+)')


def _salvage(raw: str) -> Optional[dict]:
    """Recover a label from truncated JSON.

    Measured: at max_tokens=220 roughly one response in forty was cut mid-string,
    giving "Unterminated string starting at line 1 column 10". The label sits at the
    front of the object, so it survives the truncation even when the reason does
    not, and throwing the row away would discard a perfectly good label.
    """
    m = _SALVAGE_LABEL.search(raw or "")
    if not m:
        return None
    c = _SALVAGE_CONF.search(raw)
    return {"label": m.group(1),
            "confidence": float(c.group(1)) if c else 0.0,
            "reason": "(salvaged from truncated output)"}


def label_one(llm: HostedLLM, pair_id: str, a: str, b: str,
              max_tokens: int = 400) -> Labelled:
    try:
        d = llm.json_call(LABEL_SYSTEM, _prompt(a, b), max_tokens=max_tokens)
    except json.JSONDecodeError as ex:
        d = _salvage(getattr(ex, "doc", "") or "")
        if not d:
            return Labelled(pair_id, "", 0.0, "", ok=False, error=str(ex)[:120])
    except Exception as ex:
        return Labelled(pair_id, "", 0.0, "", ok=False, error=str(ex)[:120])
    raw = str(d.get("label", "")).strip().lower()
    raw = re.sub(r"[^a-z_]", "", raw)
    if raw not in LABELS_VALID:
        return Labelled(pair_id, "", 0.0, str(d)[:80], ok=False,
                        error=f"invalid label {raw!r}")
    try:
        conf = float(d.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return Labelled(pair_id, raw, max(0.0, min(1.0, conf)),
                    str(d.get("reason", ""))[:120])


def label_consensus(llm: HostedLLM, items, rounds: int = 2,
                    min_confidence: float = 0.9,
                    concurrency: int = C.HOSTED_SAFE_CONCURRENCY,
                    progress=None):
    """Label each pair independently `rounds` times; keep only unanimous rows.

    Both filters here were measured against hand labels rather than assumed:

      no filter          90.0% bucket agreement
      rounds concur      94.4%
      confidence >= 0.9  94.4%, and 100% on the same-claim decision
      rounds disagree    50.0%, a coin flip

    So a pair the model labels differently on two passes carries no information and
    is dropped rather than kept with a lower weight. Yield is the price: roughly one
    row in six is discarded, which is cheap next to training on noise.

    Returns (kept, dropped_reasons).
    """
    passes = []
    shared = RateLimiter()
    for r in range(rounds):
        passes.append({x.id: x for x in label_many(
            llm, items, concurrency=concurrency, limiter=shared,
            progress=(lambda d, n, res, _r=r: progress(d, n, res, _r + 1, rounds))
            if progress else None)})   # noqa: E501

    kept, dropped = [], Counter()
    for pid, *_ in items:
        got = [p.get(pid) for p in passes]
        if any(g is None or not g.ok for g in got):
            dropped["error"] += 1
            continue
        labels = {g.label for g in got}
        if len(labels) > 1:
            dropped["inconsistent"] += 1
            continue
        conf = min(g.confidence for g in got)
        if conf < min_confidence:
            dropped["low_confidence"] += 1
            continue
        best = max(got, key=lambda g: g.confidence)
        kept.append(Labelled(pid, best.label, conf, best.reason))
    return kept, dropped


class RateLimiter:
    """Token bucket, because backing off after a 429 is far worse than not tripping it.

    Measured: a 32-pair burst at concurrency 8 runs at 430 requests a minute, but the
    hosted Model API caps at 120 a minute. A sustained run therefore blasts past the
    cap, collects 429s, and each one costs a fixed 2-4 second sleep. The observed
    result was 30 requests a minute, four times SLOWER than simply pacing to the cap.

    Concurrency above 8 makes it worse, not better: 16 halved throughput and 32 both
    halved it again and started dropping responses, which matches the note in
    claimtrace/baseten.py that 64 collapses entirely.
    """

    def __init__(self, per_minute: int = 110):
        self._interval = 60.0 / max(per_minute, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        import time as _t
        with self._lock:
            now = _t.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait:
            _t.sleep(wait)


def label_many(llm: HostedLLM, items, concurrency: int = C.HOSTED_SAFE_CONCURRENCY,
               progress=None, limiter: Optional[RateLimiter] = None) -> List[Labelled]:
    """items = [(id, text_a, text_b)]. Concurrency 8 is the measured healthy value;
    64 collapsed throughput to 1.4 requests a second."""
    out, lock, done = [None] * len(items), threading.Lock(), [0]
    limiter = limiter or RateLimiter()

    def work(i):
        limiter.acquire()
        res = label_one(llm, *items[i])
        out[i] = res
        if progress:
            with lock:
                done[0] += 1
                progress(done[0], len(items), res)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(work, range(len(items))))
    return [r for r in out if r is not None]


# ------------------------------------------------------------------- validation
def validate_repeated(llm: HostedLLM, rounds: int = 5, pairs_path: Optional[str] = None,
                      gating_only: bool = True, progress=None) -> dict:
    """Run validation `rounds` times and separate the two sources of noise.

    This exists because a single run is not a measurement. The same prompt on the
    same 21 pairs produced bucket agreement of 85.7%, 90.0%, 95.2% and 81.0% on four
    occasions. That 14-point spread is fully explained by sampling noise: at n=21 the
    95% binomial interval is roughly +/-13 points, so the set cannot distinguish 81%
    from 95%, and any single number quoted from it is a draw rather than a result.

    Two variances, reported separately because they have different remedies:

      model noise  spread across rounds on the same items. Shrinks by averaging
                   rounds, which is cheap.
      item noise   the binomial interval from having only n items. Shrinks ONLY by
                   hand-labelling more pairs, which is the actual bottleneck.

    Averaging rounds therefore tightens the estimate of "agreement on these items"
    and does nothing for whether those items represent the task.
    """
    import math
    import statistics

    runs = []
    for r in range(rounds):
        runs.append(validate(
            llm, pairs_path=pairs_path, gating_only=gating_only,
            progress=(lambda d, n, res, _r=r: progress(d, n, res, _r + 1, rounds))
            if progress else None))

    out = {"rounds": rounds, "n": runs[0]["n"], "runs": runs}
    for key in ("exact_agreement", "bucket_agreement", "binary_agreement"):
        vals = [r[key] for r in runs if r[key] is not None]
        if not vals:
            out[key] = None
            continue
        mean = sum(vals) / len(vals)
        n = max(runs[0]["usable"], 1)
        model_sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        item_se = math.sqrt(max(mean * (1 - mean), 1e-9) / n)
        out[key] = mean
        out[f"{key}_min"] = min(vals)
        out[f"{key}_max"] = max(vals)
        out[f"{key}_model_sd"] = model_sd
        out[f"{key}_item_se"] = item_se
        # Conservative bound: both noise sources, added in quadrature.
        out[f"{key}_lower95"] = max(0.0, mean - 1.96 * math.sqrt(
            model_sd ** 2 / max(len(vals), 1) + item_se ** 2))

    # Per-item stability: which pairs the model cannot make up its mind about.
    per_item = {}
    for r in runs:
        for row in r["rows"]:
            per_item.setdefault(row["id"], []).append(row.get("pred"))
    out["unstable_items"] = sorted(
        pid for pid, preds in per_item.items() if len(set(preds)) > 1)
    return out


def validate(llm: HostedLLM, pairs_path: Optional[str] = None,
             gating_only: bool = True, progress=None) -> dict:
    """Score the labeller against hand labels. This gates whether we trust it.

    Agreement is reported two ways. Exact is the 5-way match. Binary collapses to
    same-claim versus not, which is the decision the pipeline actually consumes, so
    a paraphrase called verbatim is a near miss rather than a failure.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eval.dataset import POSITIVE_LABELS, load

    gold = load(pairs_path) if pairs_path else load()
    if gating_only:
        gold = [g for g in gold if g.gates]
    items = [(g.id, g.reference, g.candidate) for g in gold]
    got = {r.id: r for r in label_many(llm, items, progress=progress)}

    rows, exact, binary, bucket, usable = [], 0, 0, 0, 0
    confusion = {}
    for g in gold:
        r = got.get(g.id)
        if not r or not r.ok:
            rows.append({"id": g.id, "gold": g.label, "pred": None,
                         "error": r.error if r else "missing"})
            continue
        usable += 1
        same_gold = g.label in POSITIVE_LABELS
        same_pred = r.label in POSITIVE_LABELS
        exact += r.label == g.label
        binary += same_gold == same_pred
        bucket += collapse(g.label) == collapse(r.label)
        confusion.setdefault(g.label, {}).setdefault(r.label, 0)
        confusion[g.label][r.label] += 1
        rows.append({"id": g.id, "gold": g.label, "pred": r.label,
                     "agree": r.label == g.label, "binary_agree": same_gold == same_pred,
                     "bucket_agree": collapse(g.label) == collapse(r.label),
                     "confidence": r.confidence, "reason": r.reason})
    return {"n": len(gold), "usable": usable,
            "exact_agreement": exact / usable if usable else None,
            "bucket_agreement": bucket / usable if usable else None,
            "binary_agreement": binary / usable if usable else None,
            "confusion": confusion, "rows": rows}


# ------------------------------------------------------------------ persistence
def apply_to(cands: List[Candidate], labelled: List[Labelled],
             min_confidence: float = 0.0) -> List[dict]:
    """Join labels back onto candidates, emitting the eval/training row schema.

    `reference` is post A and `candidate` is post B, matching eval/pairs.jsonl so a
    mined row can be promoted into the gate after hand verification without any
    reshaping.
    """
    by_id = {r.id: r for r in labelled if r.ok}
    rows = []
    for c in cands:
        r = by_id.get(c.id)
        if not r or r.confidence < min_confidence:
            continue
        rows.append({
            "id": f"bsky-{c.id}",
            "reference": c.a_text,
            "candidate": c.b_text,
            "label": r.label,
            "confidence": "machine",
            "note": r.reason,
            "source": {
                "kind": "bluesky-mined",
                "a_uri": c.a_uri, "b_uri": c.b_uri,
                "a_handle": c.a_handle, "b_handle": c.b_handle,
                "a_lang": c.a_lang, "b_lang": c.b_lang,
                "a_day": c.a_day, "b_day": c.b_day,
                "shared": c.shared, "jaccard": c.jaccard,
                "cross_lingual": c.cross_lingual,
                "label_confidence": r.confidence,
            },
        })
    return rows


def write_rows(rows: List[dict], path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)
