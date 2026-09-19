"""Easy negatives by random pairing. Free, unlimited, and no labelling call.

Mined candidates are selected for shared rare tokens inside a narrow time window,
which is a same-event filter, so the mined distribution skews hard toward positives.
Measured on a stratified sample of 106 candidates: 57% came back same_paraphrase and
only 11% unrelated.

Training on that alone teaches a model to say yes. Random cross-day, cross-outlet
pairs supply the `unrelated` mass, cost nothing, and need no model call because the
label follows from the construction rather than from a judgement.

The one real risk is a false negative: two randomly drawn posts that genuinely do
describe the same event. Guarded three ways, and the guards matter more than they
look, because a mislabelled positive sitting in the negative pile teaches exactly
the wrong thing about the pair type we are trying to fix.
"""
import random
from typing import List

from .pairs import Candidate
from .text import detect_language, jaccard, tokens

# A random pair sharing this many rare tokens is not safely unrelated.
MAX_SHARED_RARE = 1
# Nor is one with meaningful lexical overlap.
MAX_JACCARD = 0.08
# Different weeks, so a shared news cycle cannot sneak in.
MIN_DAY_GAP = 7


def _day_gap(a: str, b: str) -> int:
    from datetime import date
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 999


def build(posts: List, n: int = 400, seed: int = 0,
          rare_max_df: int = 40) -> List[Candidate]:
    """Draw `n` random pairs that pass every unrelatedness guard."""
    from collections import Counter

    rng = random.Random(seed)
    toks = {p.uri: tokens(p.claim_text, p.description) for p in posts}
    lang = {p.uri: detect_language(toks[p.uri], default=p.lang,
                                   raw=f"{p.claim_text} {p.description}")
            for p in posts}
    df = Counter()
    for t in toks.values():
        df.update(t)
    rare = {u: {w for w in t if df[w] <= rare_max_df} for u, t in toks.items()}

    pool = [p for p in posts if toks[p.uri]]
    out, seen, attempts = [], set(), 0
    while len(out) < n and attempts < n * 60:
        attempts += 1
        a, b = rng.sample(pool, 2)
        if a.handle == b.handle:
            continue
        key = tuple(sorted((a.uri, b.uri)))
        if key in seen:
            continue
        if _day_gap(a.day, b.day) < MIN_DAY_GAP:
            continue
        shared = rare[a.uri] & rare[b.uri]
        if len(shared) > MAX_SHARED_RARE:
            continue
        j = jaccard(toks[a.uri], toks[b.uri])
        if j > MAX_JACCARD:
            continue
        seen.add(key)
        out.append(Candidate(
            a_uri=a.uri, b_uri=b.uri, a_handle=a.handle, b_handle=b.handle,
            a_lang=lang[a.uri], b_lang=lang[b.uri],
            a_text=a.claim_text, b_text=b.claim_text, a_day=a.day, b_day=b.day,
            shared=len(shared), shared_tokens=sorted(shared),
            jaccard=round(j, 4), overlap=0.0,
            cross_lingual=lang[a.uri] != lang[b.uri], near_duplicate=False,
        ))
    return out


def as_rows(cands: List[Candidate]) -> List[dict]:
    """Emit training rows directly. No labelling call: the label is structural.

    `confidence` is "structural" rather than "machine" so a later audit can tell
    which rows a model touched and which came from construction alone.
    """
    return [{
        "id": f"neg-{c.id}",
        "reference": c.a_text,
        "candidate": c.b_text,
        "label": "unrelated",
        "confidence": "structural",
        "note": f"random pair, {_day_gap(c.a_day, c.b_day)}d apart, "
                f"{c.shared} shared rare tokens",
        "source": {"kind": "random-negative", "a_uri": c.a_uri, "b_uri": c.b_uri,
                   "a_handle": c.a_handle, "b_handle": c.b_handle,
                   "a_lang": c.a_lang, "b_lang": c.b_lang,
                   "a_day": c.a_day, "b_day": c.b_day,
                   "shared": c.shared, "jaccard": c.jaccard,
                   "cross_lingual": c.cross_lingual},
    } for c in cands]


# ---------------------------------------------------------------- collisions
# Same entity name, far apart in time. This is the ssi-05 / boom-01 failure and the
# fine-tune BROKE it: "Penalties for SSI are delayed" from 2017 scored 0.5415 against
# a 2026 claim about Safe Superintelligence, a false accept where the served model
# managed 0.034.
#
# The cause is traceable. The labeller itself got ssi-05 wrong, calling it
# same_paraphrase at 0.78 confidence, so training rows with the same shape carry the
# same wrong label and the model learned it. Structural collisions fix that without
# asking a model anything: the label comes from the time gap.
#
# Requires MORE shared rare tokens than the random negatives, not fewer. That is the
# point. A pair sharing three entity names three weeks apart is a hard negative; a
# pair sharing nothing is an easy one, and easy ones are already covered.
COLLISION_MIN_SHARED = 2
COLLISION_MIN_DAY_GAP = 21


def build_collisions(posts: List, n: int = 1200, seed: int = 0,
                     rare_max_df: int = 40) -> List[Candidate]:
    """Pairs sharing entity names but separated by weeks: same subject, different claim."""
    import random
    from collections import Counter, defaultdict

    rng = random.Random(seed)
    toks = {p.uri: tokens(p.claim_text, p.description) for p in posts}
    lang = {p.uri: detect_language(toks[p.uri], default=p.lang,
                                   raw=f"{p.claim_text} {p.description}")
            for p in posts}
    df = Counter()
    for t in toks.values():
        df.update(t)
    rare = {u: {w for w in t if df[w] <= rare_max_df} for u, t in toks.items()}

    # Invert on rare tokens so we can find shared-entity pairs directly rather than
    # sampling randomly and hoping, which almost never hits.
    postings = defaultdict(list)
    for p in posts:
        for w in rare[p.uri]:
            postings[w].append(p.uri)
    index = {p.uri: p for p in posts}

    pairs = Counter()
    shared_tok = defaultdict(list)
    for w, uris in postings.items():
        if len(uris) < 2 or len(uris) > 60:
            continue
        for i, a in enumerate(uris):
            for b in uris[i + 1:]:
                if index[a].handle == index[b].handle:
                    continue
                if _day_gap(index[a].day, index[b].day) < COLLISION_MIN_DAY_GAP:
                    continue
                key = (a, b) if a < b else (b, a)
                pairs[key] += 1
                if len(shared_tok[key]) < 8:
                    shared_tok[key].append(w)

    eligible = [(k, v) for k, v in pairs.items() if v >= COLLISION_MIN_SHARED]
    rng.shuffle(eligible)
    out = []
    for (a_uri, b_uri), count in eligible[:n]:
        a, b = index[a_uri], index[b_uri]
        out.append(Candidate(
            a_uri=a_uri, b_uri=b_uri, a_handle=a.handle, b_handle=b.handle,
            a_lang=lang[a_uri], b_lang=lang[b_uri],
            a_text=a.claim_text, b_text=b.claim_text, a_day=a.day, b_day=b.day,
            shared=count, shared_tokens=sorted(shared_tok[(a_uri, b_uri)]),
            jaccard=round(jaccard(toks[a_uri], toks[b_uri]), 4), overlap=0.0,
            cross_lingual=lang[a_uri] != lang[b_uri], near_duplicate=False,
        ))
    return out


def collisions_as_rows(cands: List[Candidate]) -> List[dict]:
    """`incidental`, structurally. Same names, weeks apart, so a different claim."""
    return [{
        "id": f"coll-{c.id}",
        "reference": c.a_text,
        "candidate": c.b_text,
        "label": "incidental",
        "confidence": "structural",
        "note": f"shares {c.shared} entity tokens but "
                f"{_day_gap(c.a_day, c.b_day)}d apart, so a different claim",
        "source": {"kind": "entity-collision", "a_uri": c.a_uri, "b_uri": c.b_uri,
                   "a_handle": c.a_handle, "b_handle": c.b_handle,
                   "a_lang": c.a_lang, "b_lang": c.b_lang,
                   "a_day": c.a_day, "b_day": c.b_day,
                   "shared": c.shared, "jaccard": c.jaccard,
                   "cross_lingual": c.cross_lingual},
    } for c in cands]


# ------------------------------------------------------- phrase collisions
# The hardest negative shape, and the one still failing after the first sweep. ssi-05
# is an ACRONYM referring to a different entity, and crucially the shared span is a
# whole predicate:
#
#   A  "ssi are delayed after a catastrophic security incident ... openai"
#   B  "Penalties for SSI are delayed about 12-18 months, but can cost you thousands"
#
# "SSI are delayed" appears verbatim in both, so substring matching says yes and the
# referent says no. ptf-02 also shares an exact span and IS the same claim, so a model
# cannot separate them on overlap alone. The discriminating signal is whether the
# UNSHARED content is from the same domain.
#
# Deliberately the GENERAL class, not a fix aimed at ssi-05. The n-gram must contain a
# distinctive token: pairs sharing only function-word spans like "has not yet" are
# already covered by the random negatives, and 68,155 of the 3-gram matches in this
# corpus are exactly that kind of noise.
PHRASE_N = 3
PHRASE_MAX_DF = 8          # the span must be distinctive, not boilerplate
PHRASE_MAX_JACCARD = 0.28  # above this the two may genuinely be one claim
PHRASE_MIN_DAY_GAP = 10


def _ngrams(text: str, n: int = PHRASE_N):
    import re
    from .text import normalise
    words = [w for w in re.findall(r"[a-z0-9']+", normalise(text)) if len(w) > 1]
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def build_phrase_collisions(posts: List, n: int = 3000, seed: int = 0,
                            rare_max_df: int = 40) -> List[Candidate]:
    """Pairs sharing a distinctive multi-word span but asserting different claims."""
    import random
    from collections import Counter, defaultdict

    rng = random.Random(seed)
    toks = {p.uri: tokens(p.claim_text, p.description) for p in posts}
    lang = {p.uri: detect_language(toks[p.uri], default=p.lang,
                                   raw=f"{p.claim_text} {p.description}")
            for p in posts}
    tdf = Counter()
    for t in toks.values():
        tdf.update(t)

    grams = {p.uri: _ngrams(f"{p.claim_text} {p.description}") for p in posts}
    gdf = Counter()
    for g in grams.values():
        gdf.update(g)

    # Keep only distinctive spans that carry a distinctive WORD. A span of pure
    # function words is boilerplate and its pairs are easy negatives we already have.
    inv = defaultdict(list)
    for uri, gs in grams.items():
        for g in gs:
            if not 2 <= gdf[g] <= PHRASE_MAX_DF:
                continue
            if not any(tdf.get(w, 0) <= rare_max_df for w in g.split()):
                continue
            inv[g].append(uri)

    index = {p.uri: p for p in posts}
    seen, out = set(), []
    spans = list(inv.items())
    rng.shuffle(spans)
    for span, uris in spans:
        if len(out) >= n:
            break
        for i, a in enumerate(uris):
            for b in uris[i + 1:]:
                pa, pb = index[a], index[b]
                if pa.handle == pb.handle:
                    continue
                if _day_gap(pa.day, pb.day) < PHRASE_MIN_DAY_GAP:
                    continue
                key = tuple(sorted((a, b)))
                if key in seen:
                    continue
                j = jaccard(toks[a], toks[b])
                if j > PHRASE_MAX_JACCARD:
                    continue
                seen.add(key)
                out.append(Candidate(
                    a_uri=a, b_uri=b, a_handle=pa.handle, b_handle=pb.handle,
                    a_lang=lang[a], b_lang=lang[b],
                    a_text=pa.claim_text, b_text=pb.claim_text,
                    a_day=pa.day, b_day=pb.day,
                    shared=len(toks[a] & toks[b]), shared_tokens=[span],
                    jaccard=round(j, 4), overlap=0.0,
                    cross_lingual=lang[a] != lang[b], near_duplicate=False,
                ))
    return out[:n]


def phrase_collisions_as_rows(cands: List[Candidate]) -> List[dict]:
    return [{
        "id": f"phr-{c.id}",
        "reference": c.a_text,
        "candidate": c.b_text,
        "label": "incidental",
        "confidence": "structural",
        "note": f"shares the exact span \"{c.shared_tokens[0]}\" but "
                f"{_day_gap(c.a_day, c.b_day)}d apart, so a different claim",
        "source": {"kind": "phrase-collision", "a_uri": c.a_uri, "b_uri": c.b_uri,
                   "a_handle": c.a_handle, "b_handle": c.b_handle,
                   "a_lang": c.a_lang, "b_lang": c.b_lang,
                   "a_day": c.a_day, "b_day": c.b_day,
                   "shared": c.shared, "jaccard": c.jaccard,
                   "cross_lingual": c.cross_lingual},
    } for c in cands]
