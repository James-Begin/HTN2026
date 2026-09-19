"""Tokenisation, language detection, and overlap. No dependencies, no model.

Language detection is stopword-based rather than metadata-based because the
metadata lies. Measured on 4,473 Bluesky posts, 2026-09-14:

  lemonde.fr   tags every French post `langs: ["en"]`   500 of 500 WRONG
  afp.com      omits langs on 496 of 498, and posts French on a nominally
               English account, so the account is not the language either
  reuters.com  omits langs on 472 of 500
  elpais.com   tags correctly

Trusting `langs` made all 500 Le Monde posts English, which turned French-French
pairs into "cross-lingual" training data. That single field would have quietly
poisoned the pair type we most need to fix.
"""
import re
import unicodedata
from collections import Counter
from typing import Optional

# Tokens: word-ish runs of >=3 letters, or numbers with separators. Unicode-aware
# so accented Spanish and French survive, and \W excludes digits so "2030" is
# caught by the second branch rather than split.
TOKEN = re.compile(r"[^\W\d_]{3,}|\d[\d.,]*", re.UNICODE)

# Link noise. Outlets append shorteners to headline text, and reut.rs/xyz would
# otherwise be a maximally-rare token joining nothing.
LINKISH = re.compile(r"https?://\S+|\b[\w-]+\.(?:rs|ly|co|com|org|net|fr|es)/\S+")

STOPWORDS = {
    "en": {"the", "and", "for", "with", "that", "from", "has", "have", "after",
           "was", "were", "are", "his", "her", "their", "will", "not", "but",
           "who", "you", "its", "this", "they", "been", "into", "over", "more",
           "says", "said", "than", "what", "when", "would", "could", "about"},
    "fr": {"les", "des", "une", "pour", "dans", "par", "sur", "ses", "est", "aux",
           "que", "qui", "pas", "plus", "avec", "sont", "ont", "été", "leur",
           "cette", "mais", "après", "deux", "son", "elle", "nous", "vers",
           "entre", "sans", "ainsi", "contre", "depuis", "selon", "dont"},
    "es": {"los", "las", "que", "con", "por", "para", "una", "del", "sus", "más",
           "como", "pero", "esta", "este", "sus", "han", "sido", "sobre", "entre",
           "desde", "hasta", "también", "porque", "cuando", "todo", "otro",
           "año", "años", "tras", "ante", "aunque", "según"},
    "de": {"und", "der", "die", "das", "den", "dem", "des", "ist", "nicht", "auch",
           "sich", "mit", "für", "auf", "von", "aus", "eine", "einen", "einem",
           "wird", "werden", "haben", "hat", "sind", "aber", "nach", "über",
           "wie", "noch", "nur", "bei", "sein", "durch", "beim", "kann"},
    "it": {"che", "non", "per", "con", "una", "sono", "come", "anche", "più",
           "dopo", "dalla", "della", "nel", "nella", "alla", "sul", "sulla",
           "gli", "delle", "degli", "sia", "stato", "essere", "ancora", "però",
           "quando", "tutti", "loro", "suo", "questa", "questo"},
    "nl": {"het", "een", "van", "voor", "met", "niet", "aan", "door", "over",
           "maar", "dat", "zijn", "wordt", "worden", "heeft", "hebben", "als",
           "naar", "bij", "ook", "meer", "nog", "wel", "kan", "moet", "werd",
           "deze", "hun", "haar", "waar", "omdat", "terwijl"},
    "pt": {"que", "não", "com", "para", "uma", "dos", "das", "por", "mais",
           "como", "mas", "foi", "são", "está", "estão", "ser", "tem", "têm",
           "pelo", "pela", "nos", "nas", "sobre", "após", "entre", "até",
           "quando", "seus", "suas", "isso", "esta", "este"},
}
# A word appearing in two languages' lists is not evidence for either, so strip
# every such word AUTOMATICALLY rather than by hand.
#
# Hand-maintaining this failed twice. "de" and "la" are shared by French and
# Spanish; adding Portuguese then introduced "está", which is also Spanish, and
# "El niño está aquí" started detecting as Portuguese because pt matched two shared
# words while es matched one. Computing the overlap removes the whole bug class.
_SEEN = Counter(w for sw in STOPWORDS.values() for w in sw)
_AMBIGUOUS = {w for w, n in _SEEN.items() if n > 1}
for _lang in STOPWORDS:
    STOPWORDS[_lang] -= _AMBIGUOUS

LANGUAGES = tuple(STOPWORDS)


def normalise(s: str) -> str:
    return unicodedata.normalize("NFKC", LINKISH.sub(" ", s or "")).lower()


def tokens(*parts: str) -> set:
    return set(TOKEN.findall(normalise(" ".join(p for p in parts if p))))


# Characters that are near-exclusive to one language. The stopword vote alone
# fails on short headlines, which is most of this corpus: an AFP post reading
# "Le patron d'Anthropic, Dario Amodei, a appelé samedi à ralentir..." carries only
# function words shared with Spanish, so it fell through to the English default
# and turned a French-French pair into a fake cross-lingual one.
ACCENTS = {
    "fr": "èêëûœ",
    "es": "ñ¿¡óú",
    "de": "ßäöü",
    "pt": "ãõ",
    "it": "ìò",
}
# Same disjointness rule as the stopwords, for the same reason. "à" is French AND
# Italian, "ç" French AND Portuguese, "á" Spanish AND Portuguese, so none of them
# is evidence. Enforced rather than trusted.
_ACC_SEEN = Counter(ch for chars in ACCENTS.values() for ch in chars)
assert not {ch for ch, n in _ACC_SEEN.items() if n > 1}, "accent sets must be disjoint"

# Non-Latin scripts, by Unicode block. Script detection is far MORE reliable than
# stopword voting, because a block is unambiguous where function words are shared.
# Checked before the stopword vote for exactly that reason.
SCRIPT_RANGES = (
    ("ar", ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    ("he", ((0x0590, 0x05FF),)),
    ("ru", ((0x0400, 0x04FF),)),
    ("el", ((0x0370, 0x03FF),)),
    ("ja", ((0x3040, 0x30FF), (0x4E00, 0x9FFF))),   # kana, and kanji shared with zh
    ("ko", ((0xAC00, 0xD7AF), (0x1100, 0x11FF))),
    ("th", ((0x0E00, 0x0E7F),)),
    ("hi", ((0x0900, 0x097F),)),
)

LATIN_SCRIPTS = frozenset({"en", "fr", "es", "de", "it", "nl", "pt"})


def detect_script(raw: str, min_share: float = 0.15) -> Optional[str]:
    """Return a non-Latin language code, or None for Latin script.

    `min_share` guards against a single stray glyph flipping the verdict: an English
    headline quoting one Arabic word is still English. Kana is checked before kanji
    because kanji alone cannot distinguish Japanese from Chinese, and kana can.
    """
    if not raw:
        return None
    letters = [ch for ch in raw if ch.isalpha()]
    if not letters:
        return None
    counts = {}
    for code, ranges in SCRIPT_RANGES:
        n = sum(1 for ch in letters
                if any(lo <= ord(ch) <= hi for lo, hi in ranges))
        if n:
            counts[code] = n
    if not counts:
        return None
    # Kana is decisive for Japanese even in small amounts, since kanji is ambiguous.
    if any(0x3040 <= ord(ch) <= 0x30FF for ch in letters):
        return "ja"
    best = max(counts, key=lambda c: counts[c])
    return best if counts[best] / len(letters) >= min_share else None


def detect_language(toks: set, default: str = "en", raw: str = "") -> str:
    """Script check, then stopword vote, then an accent tiebreak for short text.

    Script comes first because it is unambiguous: a Unicode block cannot be shared
    the way function words are. Arabic and Japanese posts carry no Latin tokens at
    all, so no amount of stopword voting would ever classify them.
    """
    script = detect_script(raw) if raw else None
    if script:
        return script
    hits = {lang: len(toks & sw) for lang, sw in STOPWORDS.items()}
    best = max(hits, key=lambda l: hits[l])
    rest = max((v for l, v in hits.items() if l != best), default=0)
    if hits[best] >= 2 and hits[best] > rest:
        return best

    # Fall back to orthography before falling back to the default.
    text = (raw or " ".join(toks)).lower()
    marks = {lang: sum(text.count(ch) for ch in chars) for lang, chars in ACCENTS.items()}
    top = max(marks, key=lambda l: marks[l])
    if marks[top] >= 1 and marks[top] > max(
            (v for l, v in marks.items() if l != top), default=0):
        return top
    if hits[best] >= 1 and hits[best] > rest:
        return best
    return default


def jaccard(a: set, b: set) -> float:
    return len(a & b) / max(len(a | b), 1)


def overlap_coefficient(a: set, b: set) -> float:
    """|A n B| / min(|A|,|B|). Fairer than Jaccard when one text is much shorter,
    which is constantly the case: a bare headline against a headline plus lede."""
    return len(a & b) / max(min(len(a), len(b)), 1)
