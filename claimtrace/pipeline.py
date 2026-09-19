"""The pipeline: extract -> shape -> route -> (verify | lineage) -> judge -> compose."""
import json
import re
import statistics
from datetime import datetime, timedelta

from . import config as C
from .baseten import CrossEncoder, HostedLLM
from .xapi import XClient, is_handle, now_safe, sanitize_query

# --------------------------------------------------------------------- extract
# The query policy below is measured, not intuited:
#   baseline hand-written query        73.9% precision
#   + lang:en                          77.3%
#   drop the ambiguous acronym          0.0%  <- destroys recall, never do this
#   acronym + exact anchor             94.4%
#   anchor phrase alone               100.0%  <- and found 2 true positives we missed
EXTRACT_SYSTEM = """You turn a social-media claim into a search plan. Reply with JSON only.

Rules, derived from measurement:
1. `anchors` is 2-3 CANDIDATE phrases, 3-6 words each, copied EXACTLY from the
   text, ordered most distinctive first. We measure each one's real volume and
   pick the rarest, so offer genuinely different options rather than variations.
   Prefer unusual word combinations over generic ones: "catastrophic security
   incident" is a far better anchor than "ssi are delayed", because the latter
   collides with Supplemental Security Income and traced to an unrelated 2017 post.
2. `disambiguators` ADD specificity for ambiguous tokens. Never propose removing a
   term: dropping an ambiguous acronym took recall to zero in testing.
3. `morphology` lists inflectional variants of the anchor. Inflection alone cost
   12% of matched volume in testing (e.g. "pacing" vs "pace").
4. `negatives` are phrases that would collide with the anchor but mean something
   else (e.g. a foreign-language honorific, a sports chant, a brand name).
5. `premises` decomposes the claim into independently checkable assertions. A claim
   can attach a false statement to a true adjacent event; each premise is measured
   separately. Each premise's `terms` MUST be a valid X search query: bare keywords,
   "quoted phrases", and OR only. X uses IMPLICIT AND, so never write the word
   AND. No commas, no prose, max 10 words.
6. `plausibility` flags internal problems: impossible units, wrong magnitudes,
   contradictions. Be specific about the arithmetic.

Schema:
{"anchors": [str, str, str], "anchor_confidence": float, "morphology": [str],
 "disambiguators": [str], "negatives": [str], "lang": str|null,
 "subject": str (an X screen name only, or "" if unknown), "premises": [{"claim": str, "terms": str}],
 "plausibility": [str]}"""


def extract(llm: HostedLLM, text: str) -> dict:
    plan = llm.json_call(EXTRACT_SYSTEM, f"Claim:\n{text}")
    for k in ("morphology", "disambiguators", "negatives", "premises", "plausibility"):
        plan.setdefault(k, [])
    cands = plan.get("anchors") or ([plan["anchor"]] if plan.get("anchor") else [])
    cands = [c for c in (sanitize_query(c, max_words=8).replace('"', " ").strip()
                         for c in cands) if c]
    if not cands:
        words = re.findall(r"[a-z0-9']+", text.lower())
        cands = [" ".join(words[:5])]
        plan["anchor_confidence"] = 0.2
    plan["anchors"] = cands
    plan["anchor"] = cands[0]
    return plan


def pick_anchor(x: XClient, plan: dict, emit=None) -> dict:
    """Choose the anchor by MEASURED LIFT, not by rarity and not by the model.

    Rarity alone picks badly. Measured on a real claim, the rarest candidate was
    "order of magnitude more damage" at 26 posts a year, which is both the rarest
    phrase and the worst anchor: it is the vaguest part of the claim and had 1 post
    in the last 30 days. Meanwhile "catastrophic security incident" had 65 a year
    with 31 in the last 30 days.

    So the criterion is LIFT: what share of the phrase's whole history sits inside
    the current window. A phrase whose entire lifetime is this month identifies
    this event. A phrase scattered evenly across years does not.

    Counts pages are 31 days, newest first, so one paginated sweep gives both the
    recent window (first page) and the 12-month total. Same cost, right answer.
    """
    cands = plan.get("anchors") or [plan["anchor"]]
    if len(cands) < 2:
        return plan
    end = now_safe()
    start = end - timedelta(days=365)
    scored = []
    for c in cands[:3]:
        q = f'"{c}"'
        try:
            recent = total = 0
            token, pages = None, 0
            while pages < 13:
                buckets, token = x.counts(q, start, end, token)
                page = sum(b.get("tweet_count", b.get("post_count", 0)) for b in buckets)
                if pages == 0:
                    recent = page          # newest 31 days
                total += page
                pages += 1
                if not token:
                    break
        except Exception:
            continue
        lift = recent / total if total else 0.0
        scored.append((lift, recent, total, c))
        if emit:
            emit.note(f'"{c}" -> {recent:,} recent / {total:,} in 12mo, lift {lift:.0%}')
    if not scored:
        return plan
    usable = [s for s in scored if s[1] > 0] or scored   # must appear recently
    usable.sort(key=lambda s: -s[0])
    lift, recent, total, best = usable[0]
    plan["anchor"] = best
    plan["anchor_volume_12mo"] = total
    plan["anchor_lift"] = round(lift, 3)
    plan["anchor_rejected"] = [s[3] for s in usable[1:]]
    return plan


def _phrase(raw: str) -> str:
    """Wrap as an exact phrase. Model output often already contains quotes, which
    would produce `-""a" b"` and trip 'Phrases cannot be empty'."""
    s = sanitize_query(raw, max_words=8).replace('"', " ")
    s = re.sub(r"\s+", " ", s).strip()
    return f'"{s}"' if s else ""


def anchor_query(plan: dict, with_negatives: bool = True, claim: str = "") -> str:
    """The anchor phrase alone measured 100% precision, so negatives are a
    refinement rather than a requirement.

    Two guards, both from observed failures:
      * A negative must not be a substring of the anchor.
      * A negative must not appear ANYWHERE IN THE CLAIM. The model proposed
        excluding "catastrophic security incident" as a collision, but that phrase
        is in the claim, so negating it excluded the claim and the run abstained
        with zero volume despite the anchor alone matching 43 posts.
    """
    q = _phrase(plan.get("anchor", ""))
    if not q:
        raise ValueError("no usable anchor phrase")
    if not with_negatives:
        return q
    haystack = (claim or "").lower()
    anchor_core = q.strip('"').lower()
    for neg in plan.get("negatives", [])[:3]:
        n = _phrase(neg)
        if not n:
            continue
        core = n.strip('"').lower()
        if core in anchor_core or (haystack and core in haystack):
            continue      # would exclude the very thing we are looking for
        q += f" -{n}"
    return q


# ----------------------------------------------------------------------- shape
def shape(x: XClient, query: str) -> dict:
    """One flat-rate call. This is the router, not a report."""
    curve = x.daily_curve(query, days=30)
    counts = [c for _, c in curve]
    total = sum(counts)
    peak = max(counts) if counts else 0
    peak_idx = counts.index(peak) if peak else 0
    peak_day = curve[peak_idx][0] if peak else None
    med = statistics.median(counts) if counts else 0
    baseline = (statistics.median(counts[:-C.RECENT_SPIKE_DAYS])
                if len(counts) > C.RECENT_SPIKE_DAYS else med)
    ratio = peak / max(baseline, 1)
    recent = bool(peak and peak_idx >= len(counts) - C.RECENT_SPIKE_DAYS)
    # Volume strictly before the spike. This is the discriminator that matters:
    # activity before the spike means there is a history to trace. A spike out of
    # nothing has no lineage, only corroboration to check.
    pre_spike = sum(counts[:peak_idx])
    return {"curve": curve, "total_30d": total, "peak": peak, "peak_day": peak_day,
            "baseline": baseline, "spike_ratio": ratio, "spike_is_recent": recent,
            "pre_spike_total": pre_spike}


def route(sh: dict) -> str:
    """Route on whether history exists, not on whether the spike is recent.

    Caught by test_high_volume_history_routes_to_lineage: "We Must Pace the
    Frontier" has 16,679 posts and a first instance a month old, yet a
    recency-first rule sent it to VERIFY.
    """
    if sh["total_30d"] == 0:
        return "ABSTAIN"
    if sh.get("pre_spike_total", 0) >= C.MIN_PRE_SPIKE_FOR_LINEAGE:
        return "LINEAGE"
    if sh["total_30d"] < C.MIN_TOTAL_FOR_LINEAGE:
        return "VERIFY"
    if sh["spike_is_recent"] and sh["spike_ratio"] >= C.SPIKE_RATIO:
        return "VERIFY"
    return "LINEAGE"


# ---------------------------------------------------------------------- verify
def verify(x: XClient, plan: dict, base_q: str, authority_list: str = None) -> dict:
    """Corroboration by expected-absence. All flat-rate counts, ~4 cents.

    Every signal is independently guarded: a model-generated query that the
    search grammar rejects must degrade to None, not abort the run.
    """
    end = now_safe()
    start = end - timedelta(days=7)

    def safe_total(q, label):
        q = q.strip()
        if not q:
            return None
        try:
            return x.counts_total(q, start, end)
        except Exception as ex:
            print(f"    (skipped {label}: {str(ex)[:70]})")
            return None

    sig = {"raw": safe_total(base_q, "raw") or 0}
    sig["verified_only"] = safe_total(f"{base_q} is:verified", "verified")
    sig["originals_only"] = safe_total(f"{base_q} -is:retweet", "originals")
    if authority_list:
        sig["authority"] = safe_total(f"{base_q} list:{authority_list}", "authority")

    subj = plan.get("subject") or ""
    if is_handle(subj):
        sig["subject_speaks"] = safe_total(f"from:{subj.lstrip('@')}", "subject")
    elif subj:
        sig["subject_note"] = f"not a handle, skipped: {subj[:48]}"

    sig["premises"] = []
    for p in plan.get("premises", [])[:3]:
        terms = sanitize_query(p.get("terms") or p.get("claim", ""))
        if not terms:
            continue
        vol = safe_total(terms, "premise")
        if vol is not None:
            sig["premises"].append({"claim": p.get("claim", ""), "query": terms,
                                    "volume_7d": vol})

    if sig["raw"] and sig.get("originals_only") is not None:
        sig["retweet_share"] = round(1 - sig["originals_only"] / sig["raw"], 3)
    else:
        sig["retweet_share"] = None
    return sig


# --------------------------------------------------------------------- lineage
def lineage(x: XClient, base_q: str, min_likes: int = 2000, emit=None) -> dict:
    first, meta = x.earliest(base_q, emit=emit)
    try:
        top = x.cascade(base_q, min_likes=min_likes)
    except Exception:
        top = []
    return {"earliest": first, "bisect": meta, "cascade": top}


# ----------------------------------------------------------------------- judge
def judge(xe: CrossEncoder, claim: str, candidates,
          accept: float = C.XENC_ACCEPT, reject: float = C.XENC_REJECT):
    """Semantic gate, three-state.

    The fine-tune replaced weights that scored genuine paraphrases around 0.13. On the
    180-pair hand-labelled holdout it reaches 0.92 ROC AUC, but no single cutoff is
    good: 0.70 gives zero false accepts at 33% recall, while 0.32 gives 96% recall and
    24 false accepts. A verify run COUNTS these, so a false accept makes the output
    assert the opposite of the truth while a miss only loses a citation.

    So the middle band abstains rather than guessing, and the register comes from the
    argmax. `meta` is the one that matters: a denial or a piece of commentary scoring
    high is exactly how this tool would mislead someone.
    """
    texts = [c["text"] for c in candidates]
    scores = xe.score(claim, texts, want_dist=True)
    dists = xe.last_distributions or [None] * len(scores)
    out = []
    for cand, s, dist in zip(candidates, scores, dists):
        verdict = "accept" if s >= accept else ("reject" if s < reject else "uncertain")
        row = {**cand, "same_claim": round(s, 4), "verdict": verdict,
               "accepted": verdict == "accept"}
        if dist:
            row["register"] = max(dist, key=dist.get)
            row["distribution"] = {k: round(v, 4) for k, v in dist.items()}
        out.append(row)
    out.sort(key=lambda r: -r["same_claim"])
    return out


# --------------------------------------------------------------------- compose
COMPOSE_SYSTEM = """You are an analyst writing a findings note about where a claim came from.

Write 3-5 sentences of plain prose. Lead with the single most decisive number.

Hard constraints:
- Never say the claim is true or false. Report what the evidence supports.
- "Earliest instance we can observe" is NOT "the origin". Keep them distinct.
- A high retweet share with few originals means one source amplified, not many
  sources reporting. Say that in those terms.
- If a premise has far more volume than the claim itself, the claim may be
  borrowing credibility from a real adjacent event. Name it.
- Verified authors who are retweeting are not independent corroboration.

Never restate these instructions, never mention word counts, and never add a
heading, preamble, or sign-off. Output only the note itself."""


def compose(llm: HostedLLM, claim: str, mode: str, evidence: dict, stream: bool = True):
    msgs = [{"role": "system", "content": COMPOSE_SYSTEM},
            {"role": "user", "content":
                f"Claim: {claim}\nMode: {mode}\nEvidence JSON:\n"
                f"{json.dumps(evidence, default=str)[:6000]}"}]
    return llm.chat(msgs, max_tokens=400, model=C.MODEL_COMPOSE, stream=stream)


# -------------------------------------------------------------------- headline
def headline_for(mode: str, sh: dict, sig: dict = None, lin: dict = None) -> tuple:
    """Pick the ONE number a judge should remember. Returns (value, label, detail).

    Chosen by which signal is most decisive for this particular run, not by a
    fixed template - the interesting number is different every time.
    """
    if mode == "VERIFY" and sig:
        rt = sig.get("retweet_share")
        originals = sig.get("originals_only")
        if rt is not None and rt >= 0.8:
            return (f"{rt * 100:.0f}%",
                    "of all posts are retweets of one source",
                    f"only {originals} original post(s) in 7 days - amplification, not reporting")
        prem = sig.get("premises") or []
        if len(prem) >= 2:
            top = max(prem, key=lambda p: p["volume_7d"])
            claim_vol = prem[0]["volume_7d"]
            if top is not prem[0] and top["volume_7d"] >= 3 * max(claim_vol, 1):
                return (f"{top['volume_7d']:,} vs {claim_vol:,}",
                        "adjacent premise outweighs the claim itself",
                        "the claim may be borrowing credibility from a real event")
        if sig.get("subject_speaks") == 0:
            return ("0", "posts from the subject of the claim",
                    "the party named has said nothing about it")
        return (f"{sig.get('raw', 0):,}", "posts in 7 days", None)

    if mode == "LINEAGE" and lin and lin.get("earliest"):
        first = lin["earliest"]
        peak_day = sh.get("peak_day") or ""
        try:
            gap = (datetime.fromisoformat(peak_day) -
                   datetime.fromisoformat(first["created_at"].replace("Z", "+00:00")).replace(tzinfo=None))
            days = abs(gap.days)
            if days >= 2:
                return (f"{days} days",
                        "between the first instance and the spike",
                        f"earliest {first['created_at'][:10]}, peak {peak_day}")
        except Exception:
            pass
        return (first["created_at"][:10], "earliest instance found",
                f"{lin['bisect']['probes']} probes across 20 years of archive")

    return (f"{sh.get('total_30d', 0):,}", "posts in 30 days", None)


# ------------------------------------------------------------------ orchestrate
def run(text: str, emit, llm: HostedLLM, xe: CrossEncoder, x: XClient,
        mode: str = "auto", min_likes: int = 2000, authority_list: str = None,
        source: str = None) -> dict:
    """Full flow. Everything observable goes out through `emit`."""
    emit.claim(text, source)

    emit.stage(1, "extract")
    plan = extract(llm, text)
    plan = pick_anchor(x, plan, emit)
    emit.extract(plan)

    emit.stage(2, "shape", "1 flat-rate call")
    bare_q = anchor_query(plan, with_negatives=False)
    try:
        base_q = anchor_query(plan, claim=text)
        sh = shape(x, base_q)
    except RuntimeError:
        emit.note("query rejected by the search grammar, falling back to the bare anchor")
        base_q, sh = bare_q, shape(x, bare_q)
    # A refinement that produces nothing is worse than no refinement.
    if sh["total_30d"] == 0 and base_q != bare_q:
        emit.note("negatives eliminated every match, retrying with the bare anchor")
        base_q, sh = bare_q, shape(x, bare_q)
    emit.shape(sh)

    chosen = route(sh) if mode == "auto" else mode.upper()
    why = {"VERIFY": "spike with no prior history",
           "LINEAGE": f"{sh.get('pre_spike_total', 0):,} posts before the spike",
           "ABSTAIN": "no measurable presence"}.get(chosen)
    emit.route(chosen, why)

    if chosen == "ABSTAIN":
        emit.done(x.spend, 0)
        return {"mode": chosen, "shape": sh}

    sig = lin = None
    candidates = []

    if chosen == "VERIFY":
        emit.stage(3, "corroboration", "flat-rate counts")
        sig = verify(x, plan, base_q, authority_list)
        emit.signal("raw 7d", sig["raw"])
        for label, key in (("verified authors", "verified_only"),
                           ("originals, no RT", "originals_only"),
                           ("authority list", "authority")):
            if key in sig:
                emit.signal(label, sig[key])
        if "subject_speaks" in sig:
            emit.signal("subject's own posts", sig["subject_speaks"], share=0.0)
        if sig.get("retweet_share") is not None:
            emit.signal("retweet share", None, share=sig["retweet_share"])
        for p in sig["premises"]:
            emit.premise(p["claim"], p["query"], p["volume_7d"])

        emit.stage(4, "candidates")
        rows = x.cascade(base_q, min_likes=1, days=2, limit=50)
        emit.cascade(rows)
        candidates = [{"text": r["text"], "created_at": r["created_at"],
                       "likes": r["public_metrics"]["like_count"]} for r in rows]
    else:
        emit.stage(3, "bisect", "misses are free")
        lin = lineage(x, base_q, min_likes=min_likes, emit=emit)
        emit.earliest(lin["earliest"], probes=lin["bisect"]["probes"])
        emit.stage(4, "cascade", "top posts only")
        emit.cascade(lin["cascade"])
        candidates = [{"text": r["text"], "created_at": r["created_at"],
                       "likes": r["public_metrics"]["like_count"]}
                      for r in lin["cascade"][:40]]
        if lin["earliest"]:
            e = lin["earliest"]
            candidates.append({"text": e["text"], "created_at": e["created_at"],
                               "likes": e["public_metrics"]["like_count"]})

    if candidates:
        emit.stage(5, "semantic gate", "dedicated cross-encoder")
        try:
            scored = judge(xe, text, candidates)
            for s in scored[:8]:
                emit.score(s["text"], s["same_claim"], s["accepted"],
                           s.get("created_at"), s.get("likes"),
                           verdict=s.get("verdict"), register=s.get("register"))
            counts = {}
            for s in scored:
                counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
            emit.note("gate: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                      + f"  (accept >= {C.XENC_ACCEPT}, reject < {C.XENC_REJECT})")
        except Exception as ex:
            emit.note(f"cross-encoder unavailable: {str(ex)[:90]}")

    emit.headline(*headline_for(chosen, sh, sig, lin))

    emit.stage(6, "findings")
    evidence = {"shape": {k: v for k, v in sh.items() if k != "curve"},
                "corroboration": sig, "lineage": None}
    if lin and lin.get("earliest"):
        e = lin["earliest"]
        evidence["lineage"] = {"earliest": {k: e[k] for k in ("created_at", "id", "text")},
                               "probes": lin["bisect"]["probes"]}
    try:
        for piece in compose(llm, text, chosen, evidence, stream=True):
            emit.token(piece)
    except Exception as ex:
        emit.note(f"compose failed: {str(ex)[:90]}")

    return {"mode": chosen, "shape": sh, "corroboration": sig, "lineage": lin}
