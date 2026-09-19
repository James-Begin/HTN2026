"""Candidate pair generation.

The join key is a shared EVENT, not a shared link and not a shared phrase.

Shared links were the original plan and the data killed it: outlets link their own
article, and Reuters shortens to `reut.rs`, so two outlets covering one event share
no url at all. Measured on 4,473 posts, exactly one pair had Jaccard above 0.85.

What does work is rare-token overlap inside a narrow time window. Independent
newsrooms writing about the same event reuse the proper nouns and the numbers and
almost nothing else. "Rescuers searching for 140 people after Indonesia passenger
ship sinks" and "Indonesian rescue crews searching for 140 people after ferry hit
bad weather" share the count and the country and diverge everywhere else.

Two things this yields that generation cannot:

  1. Cross-lingual pairs, free and real. Entity names survive translation while
     function words do not, so a Spanish and an English report of one event share
     almost only the entities. That is the 0.012 failure case, from real data.

  2. Same-topic-different-event hard negatives, also free. Saudi airstrikes in
     Yemen and Houthis capturing Moka land on the same day, share the same
     entities, and are NOT the same claim. Generation cannot invent these
     convincingly, and they are the negatives the served model most needs.

Known bias, stated plainly: selecting candidates by rare-token overlap excludes
paraphrases that share NO tokens, so the mined distribution is not the true
distribution. Cross-lingual pairs cover part of that gap because their content-word
overlap is near zero, but not all of it. This is why a small generated tail may
still earn a place, and why it belongs in a separate file so its contribution can
be ablated.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from .text import detect_language, jaccard, overlap_coefficient, tokens

# A token in more than this many documents is not an entity, it is vocabulary.
RARE_MAX_DF = 40

# Same-language pairs need more evidence than cross-language ones. Across a
# translation only proper nouns and numbers survive, so demanding three shared
# rare tokens throws away most true cross-lingual pairs.
MIN_SHARED_SAME_LANG = 3
MIN_SHARED_CROSS_LANG = 2

# Events cross midnight, and outlets in different timezones file on different
# calendar days. One day either side.
DAY_WINDOW = 1

# Above this the two texts are the same wire copy rather than independent writing.
NEAR_DUPLICATE_JACCARD = 0.85


@dataclass
class Candidate:
    """A pair worth asking about. Carries its own provenance so a labelled row can
    always be traced back to two real posts."""
    a_uri: str
    b_uri: str
    a_handle: str
    b_handle: str
    a_lang: str
    b_lang: str
    a_text: str
    b_text: str
    a_day: str
    b_day: str
    shared: int
    shared_tokens: List[str]
    jaccard: float
    overlap: float
    cross_lingual: bool
    near_duplicate: bool

    @property
    def id(self) -> str:
        return f"{self.a_uri.rsplit('/', 1)[-1]}_{self.b_uri.rsplit('/', 1)[-1]}"

    def as_dict(self) -> dict:
        return {"id": self.id, **asdict(self)}


def dedupe(posts: List) -> List:
    """Drop repeat postings of the same headline by the same account.

    Keyed on the account plus the normalised token set rather than the raw string,
    because outlets re-post with the shortener swapped or an emoji added, which a
    string comparison misses entirely.
    """
    seen, out = set(), []
    for p in posts:
        key = (p.handle, frozenset(tokens(p.claim_text, p.description)))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _day_keys(day: str, window: int) -> List[str]:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return [day]
    return [(d + timedelta(days=k)).isoformat() for k in range(-window, window + 1)]


def build(posts: List, rare_max_df: int = RARE_MAX_DF,
          min_same: int = MIN_SHARED_SAME_LANG,
          min_cross: int = MIN_SHARED_CROSS_LANG,
          day_window: int = DAY_WINDOW,
          max_pairs: Optional[int] = None) -> List[Candidate]:
    """Generate candidates via an inverted index on rare tokens.

    An inverted index rather than all-pairs because all-pairs is quadratic in the
    corpus and this corpus is meant to grow into the hundreds of thousands.
    """
    # Outlets repost the same headline, sometimes minutes apart. Left in, one
    # duplicated post multiplies into duplicate candidate pairs that look like
    # independent evidence and would be labelled and trained on twice.
    posts = dedupe(posts)

    toks: Dict[str, set] = {}
    lang: Dict[str, str] = {}
    for p in posts:
        # Join on the translation when present; keep detection on the original.
        # Detecting from the translation would relabel every Arabic post English and
        # collapse cross_lingual to False, destroying the signal being mined.
        toks[p.uri] = tokens(p.join_text, "" if p.translation else p.description)
        lang[p.uri] = detect_language(
            tokens(p.claim_text, p.description), default=p.lang,
            raw=f"{p.claim_text} {p.description}")

    df = Counter()
    for t in toks.values():
        df.update(t)

    rare = {uri: {w for w in t if df[w] <= rare_max_df} for uri, t in toks.items()}
    index = {p.uri: p for p in posts}

    # token -> day -> [uri]. Bucketing by day inside the postings list keeps the
    # inner loop over same-day-ish posts only.
    postings = defaultdict(lambda: defaultdict(list))
    for p in posts:
        for w in rare[p.uri]:
            postings[w][p.day].append(p.uri)

    shared_counts = Counter()
    shared_tokens = defaultdict(list)
    for w, days in postings.items():
        for day, uris in days.items():
            neighbours = []
            for k in _day_keys(day, day_window):
                if k >= day:                     # each unordered day pair once
                    neighbours.extend(days.get(k, []))
            for a in uris:
                for b in neighbours:
                    if a >= b:
                        continue
                    if index[a].handle == index[b].handle:
                        continue
                    key = (a, b)
                    shared_counts[key] += 1
                    if len(shared_tokens[key]) < 12:
                        shared_tokens[key].append(w)

    out = []
    for (a_uri, b_uri), n in shared_counts.items():
        a, b = index[a_uri], index[b_uri]
        la, lb = lang[a_uri], lang[b_uri]
        cross = la != lb
        if n < (min_cross if cross else min_same):
            continue
        ta, tb = toks[a_uri], toks[b_uri]
        j = jaccard(ta, tb)
        out.append(Candidate(
            a_uri=a_uri, b_uri=b_uri, a_handle=a.handle, b_handle=b.handle,
            a_lang=la, b_lang=lb, a_text=a.claim_text, b_text=b.claim_text,
            a_day=a.day, b_day=b.day, shared=n,
            shared_tokens=sorted(shared_tokens[(a_uri, b_uri)]),
            jaccard=round(j, 4),
            overlap=round(overlap_coefficient(ta, tb), 4),
            cross_lingual=cross, near_duplicate=j >= NEAR_DUPLICATE_JACCARD,
        ))

    # Most evidence first, then least lexical overlap. The head of this list is
    # where the interesting pairs are: strong entity agreement, different words.
    out.sort(key=lambda c: (-c.shared, c.jaccard))
    return out[:max_pairs] if max_pairs else out


def stats(cands: List[Candidate]) -> str:
    if not cands:
        return "no candidates"
    xl = [c for c in cands if c.cross_lingual]
    dup = [c for c in cands if c.near_duplicate]
    langs = Counter(tuple(sorted((c.a_lang, c.b_lang))) for c in xl)
    pairs = Counter(tuple(sorted((c.a_handle, c.b_handle))) for c in cands)
    js = sorted(c.jaccard for c in cands)
    lines = [
        f"{len(cands)} candidates",
        f"  cross-lingual   {len(xl)}  " + ", ".join(
            f"{a}-{b}:{n}" for (a, b), n in langs.most_common(5)),
        f"  near-duplicate  {len(dup)}  (wire copy, label as same_verbatim)",
        f"  jaccard         p25 {js[len(js) // 4]:.3f}  median "
        f"{js[len(js) // 2]:.3f}  p75 {js[3 * len(js) // 4]:.3f}",
        "  top outlet pairs: " + ", ".join(
            f"{a.split('.')[0]}+{b.split('.')[0]}:{n}" for (a, b), n in pairs.most_common(4)),
    ]
    return "\n".join(lines)
