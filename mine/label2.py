"""Cascaded labeller: ask the two questions separately instead of choosing among five.

The 5-way prompt was measured against 205 hand labels and fails in one specific place:

    meta              3 of 21 correct   =  14%
    same_paraphrase  65 of 80 correct   =  81%
    incidental       22 of 26 correct   =  85%
    same_verbatim    25 of 25 correct   = 100%

`meta` is not slightly wrong, it is mostly noise, and it gets split almost evenly into
`same_paraphrase` (8) and `incidental` (8). Those two errors have opposite causes, which
is the tell that a single 5-way choice is the wrong question shape: the model is being
asked to weigh "is this about the claim" and "does this assert the same thing" in one
step, and it collapses them.

So they are asked separately:

  STAGE 1  Is B a RESPONSE to A, or an independent assertion?   -> meta or not
  STAGE 2  Does B assert the same thing as A?                    -> same or not
  STAGE 3  Subtype, cheap and low-stakes: verbatim vs paraphrase,
           incidental vs unrelated.

Stage 3 runs without a model call. `same_verbatim` is already 100% accurate from the
5-way prompt and is trivially decidable from string containment, and the
incidental/unrelated split is not load-bearing: nothing downstream distinguishes them,
and they collapse to one bucket in every metric.
"""
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from claimtrace import config as C
from claimtrace.baseten import HostedLLM

from .label import RateLimiter, _salvage
from .outlets import HANDLES
from .text import normalise, tokens

OUTLET_HANDLES = frozenset(HANDLES)

# A curated newsroom account does not reply to another newsroom. Measured on 180
# reference pairs carrying provenance:
#
#                     B is an outlet   B is a reply
#   meta                           1             20
#   same_paraphrase               78              2
#   same_verbatim                 25              0
#   incidental                    26              0
#
# So `meta` is 20 of 23 among replies and 1 of 157 among outlet posts. Running the meta
# detector on outlet pairs is what wrecked the first cascade: it fired on an obituary,
# on a crash report quoting the mayor, and on a flood explainer, all independent reports
# that merely FRAME the story through a reaction. Precision capped at 62% and confidence
# did not separate, because the model was being asked a question the data already
# answers structurally.


def b_is_outlet(source: dict) -> bool:
    return bool(source) and source.get("b_handle") in OUTLET_HANDLES

# --------------------------------------------------------------------- stage 1
META_SYSTEM = """Decide whether POST B is a RESPONSE to the claim in POST A, or an
INDEPENDENT assertion of its own.

Reply with JSON only: {"response": true|false, "confidence": 0-1, "reason": "<=10 words"}

"response": true  - B reacts to, comments on, argues with, agrees with, denies,
  corrects, fact-checks, questions the source of, jokes about, or reports other
  people's reactions to what A says. B only makes sense because A was said.
  Includes: a reply calling the claim disgusting; a reply saying "source?"; a reply
  saying "this checks out, three outlets confirm it"; a reply extending A's argument;
  a quoted lyric used as commentary; an insult aimed at A's subject; a news report
  whose news value IS someone's reaction to A.

"response": false - B asserts something about the world on its own terms. It would
  still make sense if A had never been posted. Includes: two outlets independently
  reporting one event; a report of a DIFFERENT event; anything unrelated; and a
  restatement of A's fact by someone reporting it themselves rather than reacting.

The hard boundary, stated as a test: does B presuppose that A was SAID?
  "Russians want the empire back, they've been brainwashed"  under a war report
      -> true. It is arguing with the report's framing.
  "Rescuers search for 140 after ferry sinks"  under another ferry report
      -> false. It reports the event itself.

Endorsement is a response. Someone writing "I agree with X that we must slow down" is
responding, not announcing. But an outlet reporting the same underlying fact is not
responding, however similar the wording."""

# --------------------------------------------------------------------- stage 2
SAME_SYSTEM = """Decide whether POST B asserts THE SAME THING as POST A.

Reply with JSON only: {"same": true|false, "confidence": 0-1, "reason": "<=10 words"}

"same": true - a reader would learn the same fact about the same occurrence. Different
  words are fine. DIFFERENT LANGUAGES are fine. One text emphasising a detail the other
  omits is fine: two reports of one announcement are the same claim even if one names a
  venue and the other does not.

"same": false - B asserts something else. Be strict, because this is the common trap.
  All of these are FALSE:
    - a preview of an event vs the result of that event
    - "missing" vs "confirmed dead"; "wants to" vs "has"; "approved" vs "will vote"
    - two different totals for one running story: 20 million vs 32 million donated,
      one body found vs two bodies found
    - two separate incidents that resemble each other: two bus crashes that each
      killed 25 people are NOT the same claim
    - the same named person or acronym referring to a DIFFERENT thing. "SSI" as a
      company and "SSI" as a government benefit share no referent.
    - the event itself vs a later legal or procedural step in it

Check the ENTITIES are the same entities before deciding the claims match. Identical
wording about different referents is the single most expensive error to make."""


@dataclass
class Cascaded:
    id: str
    label: str
    confidence: float
    reason: str
    ok: bool = True
    error: str = ""
    stage: str = ""


def _ask(llm: HostedLLM, system: str, a: str, b: str, key: str,
         max_tokens: int = 300):
    """Returns (bool_answer, confidence, reason) or None on failure."""
    prompt = f"POST A:\n{a[:600]}\n\nPOST B:\n{b[:600]}"
    try:
        d = llm.json_call(system, prompt, max_tokens=max_tokens)
    except json.JSONDecodeError as ex:
        raw = getattr(ex, "doc", "") or ""
        m = re.search(rf'"{key}"\s*:\s*(true|false)', raw)
        if not m:
            return None
        c = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw)
        return (m.group(1) == "true", float(c.group(1)) if c else 0.0, "(salvaged)")
    except Exception:
        return None
    val = d.get(key)
    if isinstance(val, str):
        val = val.strip().lower() in ("true", "yes", "1")
    if not isinstance(val, bool):
        return None
    try:
        conf = float(d.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return bool(val), max(0.0, min(1.0, conf)), str(d.get("reason", ""))[:120]


# --------------------------------------------------------------------- stage 3
def _is_verbatim(a: str, b: str) -> bool:
    """String containment, no model call.

    `same_verbatim` was already 100% accurate from the 5-way prompt, and the definition
    is mechanical: identical text, a truncation, or a difference only in spelling,
    punctuation or an RT prefix. Token containment decides it without asking.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small & big) / len(small) < 0.92:
        return False
    na, nb = normalise(a), normalise(b)
    stripped = re.sub(r"^rt @[\w.]+:\s*", "", min(na, nb, key=len))
    return stripped[:40] in max(na, nb, key=len) or len(small) / len(big) > 0.55


def label_one(llm: HostedLLM, pair_id: str, a: str, b: str,
              skip_meta: bool = False) -> Cascaded:
    """`skip_meta` when B is a curated outlet: such a post is never a response, so the
    stage-1 question is skipped rather than asked and gotten wrong. Also halves the
    call count on the 11,642 outlet-B rows."""
    c1, r1 = 1.0, ""
    if not skip_meta:
        meta = _ask(llm, META_SYSTEM, a, b, "response")
        if meta is None:
            return Cascaded(pair_id, "", 0.0, "", ok=False, error="stage1 failed")
        is_response, c1, r1 = meta
        if is_response:
            return Cascaded(pair_id, "meta", c1, r1, stage="1")

    same = _ask(llm, SAME_SYSTEM, a, b, "same")
    if same is None:
        return Cascaded(pair_id, "", 0.0, "", ok=False, error="stage2 failed")
    is_same, c2, r2 = same
    conf = min(c1, c2)
    if is_same:
        return Cascaded(pair_id,
                        "same_verbatim" if _is_verbatim(a, b) else "same_paraphrase",
                        conf, r2, stage="2")
    # incidental vs unrelated is not load-bearing: nothing downstream distinguishes
    # them and they share a bucket in every metric. Decided by shared entity, free.
    shared = tokens(a) & tokens(b)
    return Cascaded(pair_id, "incidental" if len(shared) >= 2 else "unrelated",
                    conf, r2, stage="2")


def label_many(llm: HostedLLM, items, concurrency: int = C.HOSTED_SAFE_CONCURRENCY,
               limiter: Optional[RateLimiter] = None, progress=None) -> List[Cascaded]:
    out = [None] * len(items)
    limiter = limiter or RateLimiter()
    lock, done = threading.Lock(), [0]

    def work(i):
        limiter.acquire()
        item = items[i]
        # items may be (id, a, b) or (id, a, b, skip_meta)
        out[i] = label_one(llm, *item)
        if progress:
            with lock:
                done[0] += 1
                progress(done[0], len(items))

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(work, range(len(items))))
    return [r for r in out if r is not None]


# ------------------------------------------------------------------ validation
def validate(llm: HostedLLM, paths=("eval/pairs.jsonl", "eval/holdout.jsonl"),
             progress=None) -> dict:
    """Score the cascade against every hand label available.

    205 references now, against the 21 the 5-way prompt was tuned on. At n=205 the
    binomial interval on a 0.8 estimate is about +/-5 points rather than +/-17, so a
    difference between prompts can actually be believed.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eval.dataset import POSITIVE_LABELS

    gold = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                if line.strip():
                    gold.append(json.loads(line))
    gold = [g for g in gold if g.get("confidence") != "debatable"]

    got = {r.id: r for r in label_many(
        llm, [(g["id"], g["reference"], g["candidate"],
               b_is_outlet(g.get("source") or {})) for g in gold],
        progress=progress)}

    rows, exact, binary, n = [], 0, 0, 0
    per_class, conf = Counter(), {}
    tot_class = Counter()
    for g in gold:
        r = got.get(g["id"])
        if not r or not r.ok:
            continue
        n += 1
        gl = g["label"]
        tot_class[gl] += 1
        exact += r.label == gl
        per_class[gl] += r.label == gl
        binary += (r.label in POSITIVE_LABELS) == (gl in POSITIVE_LABELS)
        conf.setdefault(gl, Counter())[r.label] += 1
        rows.append({"id": g["id"], "gold": gl, "pred": r.label,
                     "agree": r.label == gl, "stage": r.stage,
                     "confidence": r.confidence, "reason": r.reason})
    return {"n": n, "exact": exact / max(n, 1), "binary": binary / max(n, 1),
            "per_class": {k: (per_class[k], tot_class[k]) for k in tot_class},
            "confusion": conf, "rows": rows}


# --------------------------------------------------------------------- hybrid
# Measured on 199 hand labels, per class, correct out of total:
#
#                     5-way prompt   cascade+gate
#   meta                 3/21  14%      24/27  89%
#   same_paraphrase     65/80  81%      61/82  74%
#   same_verbatim       25/25 100%      25/31  81%
#   incidental          22/26  85%      14/28  50%
#   unrelated           25/28  89%      28/31  90%
#
# Neither wins outright: exact agreement is 77.8% and 76.4%. But the error profiles are
# disjoint. The dedicated meta detector is six times better at the one class that
# inverts the tool's conclusion, and the 5-way prompt is better at everything else.
#
# So compose them instead of choosing. The meta question is asked separately, ONLY where
# meta can occur (B is a reply, not a newsroom), and it overrides. Every other class
# comes from the 5-way prompt, which is where it is strong.
#
# Cost is about 1.4 calls per row rather than 2, because the 11,642 outlet-B rows skip
# the meta question entirely.
def label_hybrid(llm: HostedLLM, pair_id: str, a: str, b: str,
                 source: Optional[dict] = None) -> Cascaded:
    from .label import label_one as five_way

    is_outlet = b_is_outlet(source or {})

    if not is_outlet:
        meta = _ask(llm, META_SYSTEM, a, b, "response")
        if meta and meta[0]:
            return Cascaded(pair_id, "meta", meta[1], meta[2], stage="meta-detector")

    base = five_way(llm, pair_id, a, b)
    if not base.ok:
        return Cascaded(pair_id, "", 0.0, "", ok=False, error=base.error)

    # The 5-way prompt says meta, but the meta detector did not fire, or B is a
    # newsroom where meta is 1-in-157. Resolve with the same-claim question rather
    # than keeping a label the evidence contradicts.
    if base.label == "meta":
        same = _ask(llm, SAME_SYSTEM, a, b, "same")
        if same is None:
            return Cascaded(pair_id, base.label, base.confidence, base.reason,
                            stage="5way-meta-unresolved")
        if same[0]:
            lab = "same_verbatim" if _is_verbatim(a, b) else "same_paraphrase"
        else:
            lab = "incidental" if len(tokens(a) & tokens(b)) >= 2 else "unrelated"
        return Cascaded(pair_id, lab, min(base.confidence, same[1]), same[2],
                        stage="meta-overruled")

    return Cascaded(pair_id, base.label, base.confidence, base.reason, stage="5way")


def validate_hybrid(llm: HostedLLM, paths=("eval/pairs.jsonl", "eval/holdout.jsonl"),
                    concurrency: int = C.HOSTED_SAFE_CONCURRENCY, progress=None) -> dict:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eval.dataset import POSITIVE_LABELS

    gold = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                if line.strip():
                    gold.append(json.loads(line))
    gold = [g for g in gold if g.get("confidence") != "debatable"]

    out = [None] * len(gold)
    limiter, lock, done = RateLimiter(), threading.Lock(), [0]

    def work(i):
        g = gold[i]
        limiter.acquire()
        out[i] = label_hybrid(llm, g["id"], g["reference"], g["candidate"],
                              g.get("source"))
        if progress:
            with lock:
                done[0] += 1
                progress(done[0], len(gold))

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(work, range(len(gold))))

    rows, exact, binary, n = [], 0, 0, 0
    per, tot, conf, stages = Counter(), Counter(), {}, Counter()
    for g, r in zip(gold, out):
        if not r or not r.ok:
            continue
        n += 1
        gl = g["label"]
        tot[gl] += 1
        per[gl] += r.label == gl
        exact += r.label == gl
        binary += (r.label in POSITIVE_LABELS) == (gl in POSITIVE_LABELS)
        conf.setdefault(gl, Counter())[r.label] += 1
        stages[r.stage] += 1
        rows.append({"id": g["id"], "gold": gl, "pred": r.label, "stage": r.stage,
                     "agree": r.label == gl, "confidence": r.confidence})
    return {"n": n, "exact": exact / max(n, 1), "binary": binary / max(n, 1),
            "per_class": {k: (per[k], tot[k]) for k in tot},
            "confusion": conf, "stages": dict(stages), "rows": rows}
