"""Translation bridge for non-Latin scripts. Used for MATCHING ONLY.

The problem this solves is measured, not hypothetical. The candidate join works on
shared rare tokens, which are overwhelmingly proper nouns and numbers. Across a
script boundary nothing survives:

  Al Jazeera Arabic   Latin tokens in  0 of 25 posts, Western digits in 1 of 25
  Asahi (Japanese)    Latin tokens in  1 of 15 posts

"Dario Amodei" is "داريو أمودي" in Arabic. So an Arabic post can never share a token
with an English one, and adding Arabic outlets to the corpus would contribute posts
that pair with nothing at all.

The fix keeps the training data honest. Each non-Latin post gets ONE English
translation, which is used solely to compute the join. The stored pair keeps the
ORIGINAL text, and the label is decided on the original by the same labeller as
everything else. So:

  * no generated text ever enters training. The Arabic side of a pair is real Arabic.
  * language detection reads the ORIGINAL, never the translation. Reading the
    translation would relabel every Arabic post as English and quietly collapse
    cross_lingual to False, destroying the exact signal we are mining for.
  * a wrong translation costs a bad candidate, not a bad label, because the labeller
    still judges the real texts and rejects mismatches. The failure mode is lost
    yield rather than corrupted data.

This is the same principle as the labeller: the model may help us FIND pairs, but
what we train on is text a human wrote.
"""
import json
import os
from typing import Dict, List

from claimtrace import config as C
from claimtrace.baseten import HostedLLM

from .label import RateLimiter
from .text import LATIN_SCRIPTS, detect_script

TRANSLATE_SYSTEM = """Translate the text into English. Reply with JSON only:
{"en": "..."}

Rules:
- Translate proper nouns to their standard English spelling. This is the whole point:
  "داريو أمودي" must become "Dario Amodei", not a transliteration.
- Keep numbers, dates and quantities exactly as they are.
- Do not summarise, explain, or add anything. Do not translate hashtags into prose.
- If the text is already English, return it unchanged."""


def needs_translation(post) -> bool:
    """True for posts whose script cannot share tokens with Latin text."""
    script = detect_script(f"{post.claim_text} {post.description}")
    return bool(script) and script not in LATIN_SCRIPTS


def translate_one(llm: HostedLLM, text: str, max_tokens: int = 400) -> str:
    try:
        d = llm.json_call(TRANSLATE_SYSTEM, text[:600], max_tokens=max_tokens)
    except Exception:
        return ""
    out = d.get("en") or d.get("english") or ""
    return str(out).strip()[:600]


def translate_posts(llm: HostedLLM, posts: List, concurrency: int = C.HOSTED_SAFE_CONCURRENCY,
                    progress=None) -> Dict[str, str]:
    """Returns {uri: english}. One call per post, paced to the hosted rate cap."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    targets = [p for p in posts if needs_translation(p)]
    if not targets:
        return {}
    out, lock, done = {}, threading.Lock(), [0]
    limiter = RateLimiter()

    def work(p):
        limiter.acquire()
        en = translate_one(llm, f"{p.claim_text} {p.description}".strip())
        with lock:
            if en:
                out[p.uri] = en
            done[0] += 1
            if progress:
                progress(done[0], len(targets))

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(work, targets))
    return out


# ------------------------------------------------------------------ persistence
def save(translations: Dict[str, str], path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        for uri, en in translations.items():
            fh.write(json.dumps({"uri": uri, "en": en}, ensure_ascii=False) + "\n")
    return len(translations)


def load(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                out[row["uri"]] = row["en"]
    return out


def apply_to_posts(posts: List, translations: Dict[str, str]) -> int:
    """Attach translations in place. Returns how many landed."""
    n = 0
    for p in posts:
        en = translations.get(p.uri)
        if en:
            p.translation = en
            n += 1
    return n
