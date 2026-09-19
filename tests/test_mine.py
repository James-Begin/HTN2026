"""Tests for the mining pipeline. No network, no GPU, no cost.

Several of these encode measured facts about live data, so if the upstream shape
changes the tests say so rather than the corpus quietly degrading.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mine import negatives
from mine.bluesky import Post
from mine.label import (BUCKETS, LABEL_SYSTEM, LABELS_VALID, _salvage, collapse)
from mine.pairs import build, dedupe
from mine.text import (STOPWORDS, detect_language, jaccard, normalise,
                       overlap_coefficient, tokens)


def _post(uri, handle, text, day="2026-09-14", lang="en", desc=""):
    return Post(uri=f"at://x/app.bsky.feed.post/{uri}", handle=handle, lang=lang,
                created_at=f"{day}T12:00:00Z", text=text, title=text, description=desc)


class TestText(unittest.TestCase):
    def test_strips_shortener_links(self):
        """reut.rs/abc would otherwise be a maximally rare token joining nothing."""
        t = tokens("India bars bank charges reut.rs/3T4ORT1")
        self.assertNotIn("reut", t)
        self.assertIn("india", t)

    def test_strips_full_urls(self):
        self.assertNotIn("https", tokens("story here https://example.com/a/b"))

    def test_keeps_accented_tokens_whole(self):
        t = tokens("La epidemia ha causado más muertes")
        self.assertIn("más", t)
        self.assertIn("epidemia", t)

    def test_numbers_survive_as_tokens(self):
        """Numbers are among the best cross-lingual join keys: '140 people' and
        '140 personnes' share the count when no words survive translation."""
        self.assertTrue({"140"} <= tokens("searching for 140 people"))

    def test_short_words_dropped(self):
        self.assertNotIn("of", tokens("out of the way"))

    def test_normalise_is_case_folding(self):
        self.assertEqual(normalise("ÉTÉ Ok"), "été ok")

    def test_detect_english(self):
        self.assertEqual(detect_language(tokens(
            "The court has sentenced three activists and they will appeal")), "en")

    def test_detect_french(self):
        self.assertEqual(detect_language(tokens(
            "Les dirigeants ont signé une déclaration dans laquelle par ailleurs")), "fr")

    def test_detect_spanish(self):
        self.assertEqual(detect_language(tokens(
            "Los expertos han dicho que las medidas para los ciudadanos")), "es")

    def test_accent_fallback_catches_short_french(self):
        """The real failure: an AFP headline with only shared function words fell to
        the English default, turning a French-French pair into fake cross-lingual
        training data. This is the actual post text that exposed it."""
        text = ("Le patron d'Anthropic, Dario Amodei, a appelé samedi à ralentir la "
                "vitesse de développement de l'intelligence artificielle pour mieux "
                "contrôler cette technologie")
        self.assertEqual(detect_language(tokens(text), raw=text), "fr")

    def test_accent_fallback_catches_short_spanish(self):
        text = ("Los expertos han dicho que las medidas para los ciudadanos no "
                "están todavía aprobadas según el ministerio")
        self.assertEqual(detect_language(tokens(text), raw=text), "es")

    def test_stopword_sets_are_disjoint(self):
        """A word in two languages' lists is evidence for neither. Hand-maintaining
        this failed twice: 'de'/'la' across French and Spanish, then 'está' across
        Spanish and Portuguese, which made 'El nino esta aqui' detect as Portuguese."""
        from collections import Counter
        seen = Counter(w for sw in STOPWORDS.values() for w in sw)
        self.assertFalse([w for w, n in seen.items() if n > 1])

    def test_accent_sets_are_disjoint(self):
        """'a-grave' is French AND Italian, 'c-cedilla' French AND Portuguese."""
        from collections import Counter
        from mine.text import ACCENTS
        seen = Counter(ch for chars in ACCENTS.values() for ch in chars)
        self.assertFalse([ch for ch, n in seen.items() if n > 1])

    def test_detects_arabic_script(self):
        """Arabic carries no Latin tokens at all, so only script detection works."""
        text = "الرئيس الأمريكي دونالد ترمب ينشر صورا له ولعدد من كبار المسؤولين"
        self.assertEqual(detect_language(tokens(text), raw=text), "ar")

    def test_detects_japanese_by_kana(self):
        """Kanji alone cannot separate Japanese from Chinese; kana can, so kana wins."""
        text = "ドコモはなぜつながりにくい・遅いのか　巻き返すカギは「真の5G」"
        self.assertEqual(detect_language(tokens(text), raw=text), "ja")

    def test_one_foreign_glyph_does_not_flip_the_verdict(self):
        """An English headline quoting a single Arabic word is still English."""
        text = "Trump says the OpenAI deal is off, citing الرئيس in one quoted word"
        self.assertEqual(detect_language(tokens(text), raw=text), "en")

    def test_latin_text_has_no_script_override(self):
        from mine.text import detect_script
        self.assertIsNone(detect_script("Hello world this is plain English"))

    def test_new_latin_languages_detected(self):
        for text, want in (
                ("Der Bundestag hat das Gesetz nicht beschlossen und die Regierung", "de"),
                ("Il governo non ha approvato la legge come previsto anche dopo", "it"),
                ("Het kabinet heeft het voorstel niet aangenomen voor de zomer", "nl"),
                ("O governo não aprovou a lei como previsto mais para uma", "pt")):
            self.assertEqual(detect_language(tokens(text), raw=text), want, text[:30])

    def test_falls_back_rather_than_guessing(self):
        self.assertEqual(detect_language(tokens("Zverev Shelton"), default="en"), "en")

    def test_shared_stopwords_removed_from_evidence(self):
        """'de' and 'la' appear in French and Spanish, so they cannot be evidence."""
        for lang in STOPWORDS:
            self.assertNotIn("de", STOPWORDS[lang])
            self.assertNotIn("la", STOPWORDS[lang])

    def test_jaccard_bounds(self):
        self.assertEqual(jaccard({"a"}, {"a"}), 1.0)
        self.assertEqual(jaccard({"a"}, {"b"}), 0.0)
        self.assertEqual(jaccard(set(), set()), 0.0)

    def test_overlap_coefficient_favours_containment(self):
        """A bare headline inside a headline-plus-lede should score 1.0, where
        Jaccard would penalise it for the length difference alone."""
        short, long = {"a", "b"}, {"a", "b", "c", "d"}
        self.assertEqual(overlap_coefficient(short, long), 1.0)
        self.assertLess(jaccard(short, long), 1.0)


class TestDedupe(unittest.TestCase):
    def test_drops_same_account_repost(self):
        posts = [_post("1", "a.com", "Oasis announce 2027 tour"),
                 _post("2", "a.com", "Oasis announce 2027 tour")]
        self.assertEqual(len(dedupe(posts)), 1)

    def test_drops_repost_with_shortener_swapped(self):
        """Outlets re-post with a new short link, which a string comparison misses."""
        posts = [_post("1", "a.com", "Oasis announce tour reut.rs/AAA"),
                 _post("2", "a.com", "Oasis announce tour reut.rs/BBB")]
        self.assertEqual(len(dedupe(posts)), 1)

    def test_keeps_same_text_from_different_accounts(self):
        posts = [_post("1", "a.com", "Oasis announce 2027 tour"),
                 _post("2", "b.com", "Oasis announce 2027 tour")]
        self.assertEqual(len(dedupe(posts)), 2)

    def test_drops_empty_text(self):
        self.assertEqual(dedupe([_post("1", "a.com", "")]), [])


class TestPairing(unittest.TestCase):
    def _corpus(self):
        return [
            _post("1", "reuters.com", "Zverev beats Shelton in US Open final thriller"),
            _post("2", "lemonde.fr",
                  "Alexander Zverev remporte l'US Open face à Ben Shelton au terme "
                  "d'un match dans lequel les deux joueurs ont", lang="fr"),
            _post("3", "apnews.com", "Senate passes budget bill after long debate"),
        ]

    def test_finds_the_cross_outlet_pair(self):
        cands = build(self._corpus(), min_same=2, min_cross=2)
        self.assertTrue(cands)
        ids = {frozenset((c.a_handle, c.b_handle)) for c in cands}
        self.assertIn(frozenset(("reuters.com", "lemonde.fr")), ids)

    def test_never_pairs_an_account_with_itself(self):
        posts = self._corpus() + [_post("4", "reuters.com",
                                        "Zverev beats Shelton in straight sets")]
        for c in build(posts, min_same=2, min_cross=2):
            self.assertNotEqual(c.a_handle, c.b_handle)

    def test_unrelated_posts_do_not_pair(self):
        cands = build(self._corpus(), min_same=2, min_cross=2)
        for c in cands:
            self.assertNotIn("apnews.com", (c.a_handle, c.b_handle))

    def test_cross_lingual_flag_is_set(self):
        cands = build(self._corpus(), min_same=2, min_cross=2)
        pair = [c for c in cands
                if {c.a_handle, c.b_handle} == {"reuters.com", "lemonde.fr"}][0]
        self.assertTrue(pair.cross_lingual)
        self.assertEqual({pair.a_lang, pair.b_lang}, {"en", "fr"})

    def test_day_window_excludes_distant_posts(self):
        posts = [_post("1", "a.com", "Zverev beats Shelton in US Open final"),
                 _post("2", "b.com", "Zverev beats Shelton in US Open final",
                       day="2026-08-01")]
        self.assertEqual(build(posts, min_same=2, min_cross=2, day_window=1), [])

    def test_day_window_includes_adjacent_day(self):
        """Events cross midnight and outlets file in different timezones."""
        posts = [_post("1", "a.com", "Zverev beats Shelton in US Open final"),
                 _post("2", "b.com", "Zverev beats Shelton in US Open final",
                       day="2026-09-15")]
        self.assertTrue(build(posts, min_same=2, min_cross=2, day_window=1))

    def test_cross_lingual_threshold_is_looser(self):
        """Only entities survive translation, so demanding three shared rare tokens
        discards most true cross-lingual pairs."""
        from mine.pairs import MIN_SHARED_CROSS_LANG, MIN_SHARED_SAME_LANG
        self.assertLess(MIN_SHARED_CROSS_LANG, MIN_SHARED_SAME_LANG)

    def test_candidate_id_is_stable_and_symmetric_free(self):
        cands = build(self._corpus(), min_same=2, min_cross=2)
        again = build(self._corpus(), min_same=2, min_cross=2)
        self.assertEqual([c.id for c in cands], [c.id for c in again])

    def test_no_duplicate_pairs_emitted(self):
        cands = build(self._corpus(), min_same=2, min_cross=2)
        keys = [tuple(sorted((c.a_uri, c.b_uri))) for c in cands]
        self.assertEqual(len(keys), len(set(keys)))


class TestNegatives(unittest.TestCase):
    def _corpus(self):
        """Every post has disjoint vocabulary. Shared filler like "report" would
        appear in every pair, trip the shared-rare-token guard, and reject the whole
        pool, which is exactly what an earlier version of this fixture did."""
        topics = [
            "senate budget appropriations filibuster cloture",
            "oasis gallagher knebworth reunion wembley",
            "ebola outbreak kinshasa quarantine vaccination",
            "diesel refinery pipeline haulage freight",
            "renoir museum burglary canvas gendarmes",
            "ferry capsized java rescuers lifeboats",
            "zverev shelton tennis flushing racquet",
            "afd saxony thuringia bundestag coalition",
        ]
        posts = []
        for i, words in enumerate(topics):
            for j, h in enumerate(("a.com", "b.com", "c.com")):
                posts.append(_post(f"{i}{j}", h, f"{words} {'alpha beta gamma'.split()[j]}",
                                   day=f"2026-08-{1 + i * 3:02d}"))
        return posts

    def test_all_rows_are_labelled_unrelated(self):
        rows = negatives.as_rows(negatives.build(self._corpus(), n=20))
        self.assertTrue(rows)
        self.assertTrue(all(r["label"] == "unrelated" for r in rows))

    def test_guards_hold(self):
        for c in negatives.build(self._corpus(), n=20):
            self.assertLessEqual(c.shared, negatives.MAX_SHARED_RARE)
            self.assertLessEqual(c.jaccard, negatives.MAX_JACCARD)
            self.assertNotEqual(c.a_handle, c.b_handle)

    def test_minimum_day_gap_respected(self):
        from datetime import date
        for c in negatives.build(self._corpus(), n=20):
            gap = abs((date.fromisoformat(c.a_day) - date.fromisoformat(c.b_day)).days)
            self.assertGreaterEqual(gap, negatives.MIN_DAY_GAP)

    def test_deterministic_for_a_seed(self):
        a = [c.id for c in negatives.build(self._corpus(), n=15, seed=7)]
        b = [c.id for c in negatives.build(self._corpus(), n=15, seed=7)]
        self.assertEqual(a, b)

    def test_marked_structural_not_machine(self):
        """An audit has to be able to tell which rows a model touched."""
        rows = negatives.as_rows(negatives.build(self._corpus(), n=10))
        self.assertTrue(all(r["confidence"] == "structural" for r in rows))
        self.assertTrue(all(r["source"]["kind"] == "random-negative" for r in rows))

    def test_terminates_when_the_pool_cannot_supply(self):
        tiny = [_post("1", "a.com", "one topic here"), _post("2", "a.com", "same account")]
        self.assertEqual(negatives.build(tiny, n=50), [])


class TestLabelSchema(unittest.TestCase):
    def test_buckets_cover_every_label(self):
        self.assertEqual(set(BUCKETS), LABELS_VALID)

    def test_positives_share_a_bucket(self):
        self.assertEqual(collapse("same_verbatim"), collapse("same_paraphrase"))

    def test_meta_is_its_own_bucket(self):
        """Confusing meta with a positive inverts a verify run's conclusion, so it
        must never be folded in with either side."""
        self.assertNotEqual(collapse("meta"), collapse("same_paraphrase"))
        self.assertNotEqual(collapse("meta"), collapse("unrelated"))

    def test_negatives_share_a_bucket(self):
        self.assertEqual(collapse("incidental"), collapse("unrelated"))

    def test_prompt_states_the_measured_boundary_rules(self):
        """Each rule was added because a specific disagreement exposed it. Losing one
        silently regresses agreement, so pin them."""
        for needle in ("same_verbatim", "same_paraphrase", "meta", "incidental",
                       "unrelated", "DENIES", "ACRONYM", "ANNOUNCEMENT"):
            self.assertIn(needle, LABEL_SYSTEM)

    def test_salvage_recovers_label_from_truncated_json(self):
        raw = '{"label": "same_paraphrase", "confidence": 0.93, "reason": "both asse'
        got = _salvage(raw)
        self.assertEqual(got["label"], "same_paraphrase")
        self.assertAlmostEqual(got["confidence"], 0.93)

    def test_salvage_returns_none_when_no_label(self):
        self.assertIsNone(_salvage('{"confidence": 0.9}'))
        self.assertIsNone(_salvage(""))


class TestRateLimiter(unittest.TestCase):
    """The limiter exists because exceeding the documented 120/min cap made a
    sustained run four times SLOWER than pacing to it: every 429 cost a fixed
    multi-second sleep. Pacing is not an optimisation, it is the fix."""

    def test_paces_to_the_configured_rate(self):
        import time
        from mine.label import RateLimiter
        lim = RateLimiter(per_minute=600)      # 0.1s apart
        t0 = time.monotonic()
        for _ in range(5):
            lim.acquire()
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertLess(elapsed, 1.5)

    def test_first_acquire_does_not_block(self):
        import time
        from mine.label import RateLimiter
        t0 = time.monotonic()
        RateLimiter(per_minute=1).acquire()
        self.assertLess(time.monotonic() - t0, 0.2)

    def test_is_thread_safe_under_contention(self):
        """Threads must not all be handed the same slot."""
        import threading
        import time
        from mine.label import RateLimiter
        lim = RateLimiter(per_minute=600)
        stamps, lock = [], threading.Lock()

        def work():
            lim.acquire()
            with lock:
                stamps.append(time.monotonic())

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(stamps), 8)
        self.assertGreaterEqual(max(stamps) - min(stamps), 0.55)

    def test_concurrency_default_matches_the_measured_optimum(self):
        """Measured: 8 gives 430/min, 16 gives 231/min, 32 gives 153/min and drops
        responses. Raising this constant would make things worse, not better."""
        from claimtrace import config as C
        self.assertEqual(C.HOSTED_SAFE_CONCURRENCY, 8)


class TestTranslationBridge(unittest.TestCase):
    """The bridge exists because the rare-token join is Latin-bound: Al Jazeera
    Arabic carried Latin tokens in 0 of 25 posts, so a non-Latin post pairs with
    nothing. It translates FOR MATCHING and never for training."""

    AR = "الرئيس الأمريكي دونالد ترمب ينشر صورا له ولعدد من كبار المسؤولين"
    JA = "前衛芸術家の草間彌生さん死去、97歳　世代や国境を超えて支持"

    def test_flags_non_latin_posts(self):
        from mine.translate import needs_translation
        self.assertTrue(needs_translation(_post("1", "aj.com", self.AR)))
        self.assertTrue(needs_translation(_post("2", "asahi.com", self.JA)))

    def test_does_not_flag_latin_posts(self):
        from mine.translate import needs_translation
        for text in ("Senate passes the appropriations bill today",
                     "Le gouvernement a présenté un projet de loi",
                     "Der Bundestag hat das Gesetz nicht beschlossen"):
            self.assertFalse(needs_translation(_post("x", "a.com", text)), text[:24])

    def test_join_text_prefers_the_translation(self):
        p = _post("1", "aj.com", self.AR)
        self.assertEqual(p.join_text, p.claim_text)
        p.translation = "US President Donald Trump posts photos of himself"
        self.assertEqual(p.join_text, p.translation)

    def test_claim_text_stays_original_after_bridging(self):
        """The stored training pair must be real text, never the translation."""
        p = _post("1", "aj.com", self.AR)
        p.translation = "US President Donald Trump posts photos"
        self.assertEqual(p.claim_text, self.AR)

    def test_translation_round_trips_through_the_corpus(self):
        p = _post("1", "aj.com", self.AR)
        p.translation = "US President Donald Trump"
        self.assertEqual(Post.from_dict(p.as_dict()).translation, p.translation)

    def test_pairing_joins_on_translation_but_stores_original(self):
        """The whole bridge in one assertion."""
        en = _post("1", "reuters.com",
                   "Yayoi Kusama who splashed polka dots across the art world dies at 97")
        ja = _post("2", "asahi.com", self.JA)
        self.assertEqual(build([en, ja], min_same=2, min_cross=2), [],
                         "without a translation these share no token at all")
        ja.translation = ("Avant-garde artist Yayoi Kusama dies at 97, "
                          "known for polka dots across the art world")
        cands = build([en, ja], min_same=2, min_cross=2)
        self.assertTrue(cands, "the bridge should create the pair")
        c = cands[0]
        stored = {c.a_text, c.b_text}
        self.assertIn(self.JA, stored, "the pair must store the ORIGINAL Japanese")
        self.assertNotIn(ja.translation, stored, "never store the translation")

    def test_language_detection_ignores_the_translation(self):
        """Detecting from the translation would call every Japanese post English and
        collapse cross_lingual to False, destroying the signal being mined."""
        en = _post("1", "reuters.com",
                   "Yayoi Kusama who splashed polka dots across the art world dies at 97")
        ja = _post("2", "asahi.com", self.JA)
        ja.translation = ("Avant-garde artist Yayoi Kusama dies at 97, "
                          "known for polka dots across the art world")
        c = build([en, ja], min_same=2, min_cross=2)[0]
        self.assertEqual({c.a_lang, c.b_lang}, {"en", "ja"})
        self.assertTrue(c.cross_lingual)

    def test_save_and_load_translations(self):
        import tempfile
        from mine import translate as T
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.jsonl")
            T.save({"at://a/1": "hello", "at://a/2": "world"}, path)
            self.assertEqual(T.load(path), {"at://a/1": "hello", "at://a/2": "world"})

    def test_load_missing_file_is_empty(self):
        from mine import translate as T
        self.assertEqual(T.load("/nonexistent/path.jsonl"), {})

    def test_apply_to_posts_reports_how_many_landed(self):
        from mine import translate as T
        posts = [_post("1", "a.com", self.AR), _post("2", "b.com", self.JA)]
        n = T.apply_to_posts(posts, {posts[0].uri: "translated"})
        self.assertEqual(n, 1)
        self.assertEqual(posts[0].translation, "translated")
        self.assertEqual(posts[1].translation, "")


class TestReplies(unittest.TestCase):
    """Replies are the only `meta` source available. Feed mining gave 1,466
    same_paraphrase and 34 meta, because newsrooms report rather than comment."""

    def _thread_node(self, handle, text):
        return {"post": {"uri": f"at://{handle}/app.bsky.feed.post/r{abs(hash(text)) % 999}",
                         "author": {"handle": handle},
                         "record": {"text": text, "createdAt": "2026-09-14T13:00:00Z"}}}

    def _fake_bluesky(self, replies):
        class Fake:
            calls = 0

            def _get(self, method, **params):
                return {"thread": {"post": {}, "replies": replies}}

            def report(self):
                return "fake"
        return Fake()

    def test_orientation_is_claim_then_reply(self):
        """reference must be the root claim and candidate the reply, matching the
        hand-labelled pairs where a disputing reply sits as the candidate."""
        from mine.replies import fetch
        root = _post("root", "reuters.com", "Senate passes the appropriations bill today")
        bs = self._fake_bluesky([self._thread_node(
            "someone.bsky.social", "this is completely false and no source confirms it")])
        cands = fetch(bs, [root])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].a_text, root.claim_text)
        self.assertIn("completely false", cands[0].b_text)

    def test_drops_replies_with_too_little_text(self):
        """Bare emoji and one-word replies carry no claim to compare."""
        from mine.replies import fetch
        root = _post("root", "reuters.com", "Senate passes the appropriations bill today")
        bs = self._fake_bluesky([self._thread_node("a.bsky.social", "💪"),
                                 self._thread_node("b.bsky.social", "lol ok")])
        self.assertEqual(fetch(bs, [root]), [])

    def test_drops_self_replies(self):
        """An outlet replying to itself is a thread continuation that repeats the
        parent, which would manufacture fake verbatim pairs."""
        from mine.replies import fetch
        root = _post("root", "reuters.com", "Senate passes the appropriations bill today")
        bs = self._fake_bluesky([self._thread_node(
            "reuters.com", "Read the full story on our site right here now")])
        self.assertEqual(fetch(bs, [root]), [])

    def test_respects_per_root_cap(self):
        from mine.replies import fetch
        root = _post("root", "reuters.com", "Senate passes the appropriations bill today")
        nodes = [self._thread_node(f"u{i}.bsky.social",
                                   f"here is my considered opinion number {i} about this")
                 for i in range(10)]
        self.assertEqual(len(fetch(self._fake_bluesky(nodes), [root], per_root=3)), 3)

    def test_pick_roots_spreads_across_days(self):
        from mine.replies import pick_roots
        posts = [_post(f"{d}{i}", "a.com", f"story {d} {i} happened somewhere",
                       day=f"2026-09-{d:02d}") for d in range(1, 6) for i in range(5)]
        roots = pick_roots(posts, n=5)
        self.assertEqual(len(roots), 5)
        self.assertEqual(len({r.day for r in roots}), 5,
                         "one news cycle must not dominate the sample")

    def test_pick_roots_is_deterministic(self):
        from mine.replies import pick_roots
        posts = [_post(f"{d}{i}", "a.com", f"story {d} {i} happened somewhere",
                       day=f"2026-09-{d:02d}") for d in range(1, 6) for i in range(5)]
        self.assertEqual([r.uri for r in pick_roots(posts, n=8, seed=3)],
                         [r.uri for r in pick_roots(posts, n=8, seed=3)])

    def test_pick_roots_skips_posts_without_text(self):
        from mine.replies import pick_roots
        self.assertEqual(pick_roots([_post("1", "a.com", "")], n=5), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
