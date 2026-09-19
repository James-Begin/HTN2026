"""Curated Bluesky accounts to mine. Every handle here was verified reachable.

Two things drive yield, and neither is "more pages of the same outlets":

1. OUTLET COUNT, quadratically. Candidates come from cross-outlet pairs, so 9
   outlets give 36 pairs and 29 give 406.

2. DATE-RANGE OVERLAP, not corpus size. Measured: tripling the corpus from 4,473 to
   13,412 posts raised candidates only 1,896 -> 2,673, because the extra pages
   extended backward where outlets no longer overlap. Reuters files 135 posts a day
   and covered 11 days; AFP files 17 a day and covered three months. Pairs can only
   form inside the intersection, so every outlet must be paged back to a COMMON
   FLOOR DATE rather than to a common page count.

`script` matters because the rare-token join is Latin-bound. Measured on real feeds:
Al Jazeera Arabic carried Latin tokens in 0 of 25 posts and Western digits in 1 of
25; Asahi carried Latin tokens in 1 of 15. Non-Latin outlets therefore cannot pair
with anything through token overlap and need the translation bridge in
mine/translate.py, which translates FOR MATCHING ONLY and keeps the original text in
the training pair.
"""

# handle, language, script, note
OUTLETS = [
    # ---- English ------------------------------------------------------------
    ("reuters.com",        "en", "latin", "wire, highest volume, ~135 posts/day"),
    ("apnews.com",         "en", "latin", "wire"),
    ("afp.com",            "en", "latin", "wire, posts mostly FRENCH despite the account"),
    ("theguardian.com",    "en", "latin", "distinct editorial voice from the wires"),
    ("npr.org",            "en", "latin", ""),
    ("bloomberg.com",      "en", "latin", "business framing of the same events"),
    ("aljazeera.com",      "en", "latin", "different framing, useful for meta vs same"),
    ("washingtonpost.com", "en", "latin", ""),
    ("nytimes.com",        "en", "latin", ""),
    ("cnn.com",            "en", "latin", ""),
    ("economist.com",      "en", "latin", "analysis register, low overlap wording"),
    ("politico.com",       "en", "latin", "US politics density"),
    ("axios.com",          "en", "latin", "deliberately terse house style"),
    ("theverge.com",       "en", "latin", "tech, overlaps techcrunch/ars on one story"),
    ("techcrunch.com",     "en", "latin", "tech"),
    ("arstechnica.com",    "en", "latin", "tech"),
    ("propublica.org",     "en", "latin", "investigative"),
    ("404media.co",        "en", "latin", "tech investigative"),

    # ---- French -------------------------------------------------------------
    ("lemonde.fr",         "fr", "latin", "tags every French post langs=['en'], WRONG"),
    ("liberation.fr",      "fr", "latin", ""),
    ("franceinfo.fr",      "fr", "latin", ""),
    ("rfi.fr",             "fr", "latin", "international desk, wide event coverage"),
    ("mediapart.fr",       "fr", "latin", ""),

    # ---- Spanish ------------------------------------------------------------
    ("elpais.com",         "es", "latin", "tags langs correctly, unusually"),
    ("eldiario.es",        "es", "latin", ""),

    # ---- German -------------------------------------------------------------
    ("spiegel.de",         "de", "latin", "88k posts, deepest archive of any outlet here"),
    ("zeit.de",            "de", "latin", ""),

    # ---- Italian ------------------------------------------------------------
    ("ilpost.it",          "it", "latin", ""),
    ("fanpage.it",         "it", "latin", ""),

    # ---- Dutch --------------------------------------------------------------
    ("nrc.nl",             "nl", "latin", ""),
    ("volkskrant.nl",      "nl", "latin", ""),

    # ---- Portuguese ---------------------------------------------------------
    ("publico.pt",         "pt", "latin", ""),

    # ---- Non-Latin: needs the translation bridge to join at all -------------
    ("asahi.com",          "ja", "japanese", "Asahi Shimbun. 1/15 posts had Latin tokens"),
    ("hankyoreh.bsky.social", "en", "latin", "Hankyoreh ENGLISH edition: 247/253 posts are English"),
]

# Checked and rejected, recorded so the search is not repeated:
#   ajarabic.bsky.social   Al Jazeera Arabic, 1,614 posts but DORMANT since
#                          2026-01-03, months before any usable floor date. No active
#                          Arabic news outlet was found on Bluesky at all, so the
#                          Arabic case that motivated the cross-script bridge cannot
#                          currently be sourced here. It would need X, which bills
#                          per row, or another platform.
#   bbcarabic, trtarabi    0 posts
#   jiji.bsky.social       Japanese, dormant since 2024-12-03
#   bbcnews, dwnews        0 posts despite existing
#   hankyoreh              active, but it is the ENGLISH edition. Detected en on
#                          247 of 253 posts, so it is a useful extra English outlet
#                          and NOT a Korean source. Kept, relabelled.
#
# Net position on non-Latin: only Asahi supplies real volume, 829 bridged posts and
# 141 English-Japanese candidates. Bluesky's user base is heavily Western, so the
# Arabic case that motivated the bridge is not sourceable here at all. The bridge
# itself is validated and would work the moment an Arabic feed exists.

HANDLES = [h for h, _, _, _ in OUTLETS]
LANG_OF = {h: l for h, l, _, _ in OUTLETS}
SCRIPT_OF = {h: s for h, _, s, _ in OUTLETS}

LATIN_HANDLES = [h for h, _, s, _ in OUTLETS if s == "latin"]
NONLATIN_HANDLES = [h for h, _, s, _ in OUTLETS if s != "latin"]

# Rough posts-per-day, measured, so a floor date can be turned into a page budget.
# Reuters needs ~10x the pages of AFP to reach the same date.
POSTS_PER_DAY = {
    "reuters.com": 135, "theguardian.com": 90, "lemonde.fr": 68, "bloomberg.com": 45,
    "aljazeera.com": 45, "apnews.com": 33, "elpais.com": 62, "npr.org": 23,
    "afp.com": 17, "spiegel.de": 90, "zeit.de": 60, "liberation.fr": 55,
    "nrc.nl": 50, "volkskrant.nl": 50, "eldiario.es": 55, "ilpost.it": 40,
    "publico.pt": 35, "nytimes.com": 60, "washingtonpost.com": 45, "cnn.com": 45,
    "economist.com": 40, "politico.com": 25, "axios.com": 15, "theverge.com": 25,
    "techcrunch.com": 25, "arstechnica.com": 20, "propublica.org": 10,
    "404media.co": 8, "franceinfo.fr": 25, "rfi.fr": 35, "mediapart.fr": 20,
    "fanpage.it": 25, "asahi.com": 12, "hankyoreh.bsky.social": 6,
}

DEFAULT_POSTS_PER_DAY = 30


def pages_for(handle: str, days: int, per_page: int = 100, slack: float = 1.5) -> int:
    """Pages needed to reach `days` back. Slack covers bursty news days."""
    rate = POSTS_PER_DAY.get(handle, DEFAULT_POSTS_PER_DAY)
    return max(1, int(days * rate * slack / per_page) + 1)


def cross_lingual(a: str, b: str) -> bool:
    return LANG_OF.get(a) != LANG_OF.get(b)
