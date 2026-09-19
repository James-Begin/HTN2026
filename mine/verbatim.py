"""Structural `same_verbatim` pairs by truncation. Free, no model call.

The problem: English-only mining yields 52 `same_verbatim` rows against 2,565
`unrelated`. That is not a collection failure, it is a property of the corpus, since
newsrooms rewrite rather than republish. But 52 examples cannot train a class.

Padding was considered and rejected for the obvious candidates. A post's text against
its own embed title differs only by an appended shortener, sits at Jaccard near 1.0,
and teaches nothing the served model does not already do at 0.999.

Truncation is different, and it is chosen because it matches a REAL failure the eval
set already contains. `ssi-02` is a retweet cut off mid-sentence:

    "RT @iruletheworldmo: ssi are delayed after a catastrophic security incident di"

Truncation is how claims actually propagate on a character-limited platform, and the
labelling rules already say so: rule 2 defines `same_verbatim` as covering "one text
being a truncation of the other". So these pairs are real text on both sides, labelled
by construction, and they train exactly the case the eval set tests.

Deliberately NOT generated here:
  * case-folded or emoji-stripped variants. Real but trivially easy, and they would
    inflate the count with pairs no model gets wrong.
  * paraphrases of any kind. That would be generation, which is the thing this whole
    pipeline exists to avoid.
"""
import random
from typing import List

from .text import tokens

# Truncate to somewhere in this fraction of the original. 0.45 was tried and cut too
# hard: "Three people charged with threatening judge, witnesses in Nolan Wells case"
# became "Three people charged with threatening", which is a fragment rather than a
# truncated claim. The remainder has to still ASSERT the thing.
MIN_KEEP = 0.6
MAX_KEEP = 0.85

# A truncation of a very short post is not a claim, it is a fragment.
MIN_TOKENS = 10


def _truncate(text: str, keep: float) -> str:
    """Cut at a word boundary, the way a character limit actually does."""
    target = max(1, int(len(text) * keep))
    cut = text[:target]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


def build(posts: List, n: int = 800, seed: int = 0,
          rt_prefix_share: float = 0.35) -> List[dict]:
    """Emit `n` truncation pairs as training rows.

    `rt_prefix_share` prepends a retweet marker to some fraction, because that is
    what the real case looks like and the prefix is a surface feature the model must
    learn to ignore rather than treat as evidence.
    """
    rng = random.Random(seed)
    usable = [p for p in posts
              if p.claim_text and len(tokens(p.claim_text)) >= MIN_TOKENS]
    rng.shuffle(usable)
    rows = []
    for p in usable[:n]:
        keep = rng.uniform(MIN_KEEP, MAX_KEEP)
        cut = _truncate(p.claim_text, keep)
        if not cut or cut == p.claim_text:
            continue
        if len(tokens(cut)) < 7:
            continue
        candidate = cut
        if rng.random() < rt_prefix_share:
            candidate = f"RT @{p.handle.split('.')[0]}: {cut}"
        rows.append({
            "id": f"trunc-{p.id}",
            "reference": p.claim_text,
            "candidate": candidate,
            "label": "same_verbatim",
            "confidence": "structural",
            "note": f"truncated to {keep:.0%} at a word boundary",
            "source": {"kind": "truncation", "a_uri": p.uri, "b_uri": p.uri,
                       "a_handle": p.handle, "b_handle": p.handle,
                       "a_lang": "en", "b_lang": "en",
                       "a_day": p.day, "b_day": p.day,
                       "shared": len(tokens(cut)), "jaccard": 1.0,
                       "cross_lingual": False},
        })
    return rows


# ------------------------------------------------------- length-asymmetry pairs
# The fine-tune made ptf-02 WORSE, 0.2611 down to 0.0527. That pair is the essay's
# exact title plus a link, against the full announcement:
#
#   reference  "We Must Pace the Frontier: I've written a new essay on why the AI
#               industry should slow down, with a three-part plan"
#   candidate  "We Must Pace the Frontier https://t.co/sezx1DnTZn"
#
# The truncation pairs above did not teach this, because they keep 60-85% of the text
# and this keeps a fraction of it. A very short candidate against a long reference is
# a distinct shape, and the labeller got it wrong too, calling it incidental because
# "B only shares title, no claim content".
#
# Every Bluesky post supplies exactly this shape for free and with no fabrication:
#   reference = the embed title plus the article lede  (long)
#   candidate = the post text, which is the headline plus a REAL shortener  (short)
# Both sides are real published text.
MIN_ASYMMETRY = 2.0        # reference at least this many times longer


def build_headline_pairs(posts: List, n: int = 900, seed: int = 0) -> List[dict]:
    """Short headline-plus-link against the long headline-plus-lede for one post."""
    import random

    rng = random.Random(seed)
    usable = []
    for p in posts:
        if not (p.title and p.description and p.text):
            continue
        long_side = f"{p.title} {p.description}".strip()
        short_side = p.text.strip()
        if len(long_side) < len(short_side) * MIN_ASYMMETRY:
            continue
        if len(tokens(short_side)) < 5:
            continue
        usable.append((p, long_side, short_side))
    rng.shuffle(usable)

    rows = []
    for p, long_side, short_side in usable[:n]:
        rows.append({
            "id": f"head-{p.id}",
            "reference": long_side,
            "candidate": short_side,
            "label": "same_verbatim",
            "candidate_len": len(short_side),
            "note": f"headline plus link vs headline plus lede, "
                    f"{len(long_side) / max(len(short_side), 1):.1f}x length gap",
            "confidence": "structural",
            "source": {"kind": "headline-asymmetry", "a_uri": p.uri, "b_uri": p.uri,
                       "a_handle": p.handle, "b_handle": p.handle,
                       "a_lang": "en", "b_lang": "en",
                       "a_day": p.day, "b_day": p.day,
                       "shared": len(tokens(short_side)), "jaccard": 1.0,
                       "cross_lingual": False},
        })
    for r in rows:
        r.pop("candidate_len", None)
    return rows
