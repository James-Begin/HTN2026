"""Tests for the training data pipeline and the structural generators.

No network, no GPU. Everything here is either pure logic or runs on a handful of
synthetic posts, so it belongs in the offline suite.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.dataset import LABELS, POSITIVE_LABELS
from eval.metrics import robust_separation, separation
from mine.bluesky import Post
from mine.negatives import (COLLISION_MIN_DAY_GAP, COLLISION_MIN_SHARED,
                            build_collisions, collisions_as_rows)
from mine.verbatim import build as build_trunc
from mine.verbatim import MIN_KEEP, build_headline_pairs
from train.data import (class_weights, load_rows, split_by_day, to_examples)


def _post(uri, handle, text, day="2026-09-14", desc="", title=None):
    return Post(uri=f"at://x/app.bsky.feed.post/{uri}", handle=handle, lang="en",
                created_at=f"{day}T12:00:00Z", text=text,
                title=text if title is None else title, description=desc)


class TestTruncationPairs(unittest.TestCase):
    """These exist because English-only mining yielded 52 same_verbatim rows, and
    because ssi-02 in the eval set is literally a truncated retweet."""

    def _posts(self, n=40):
        return [_post(str(i), "reuters.com",
                      f"Federal investigators detail plans for determining what caused "
                      f"the accident number {i} in the state capital yesterday")
                for i in range(n)]

    def test_labels_are_same_verbatim(self):
        rows = build_trunc(self._posts(), n=10)
        self.assertTrue(rows)
        self.assertTrue(all(r["label"] == "same_verbatim" for r in rows))

    def test_candidate_is_shorter_than_reference(self):
        for r in build_trunc(self._posts(), n=10):
            body = r["candidate"].split(": ", 1)[-1] if r["candidate"].startswith("RT @") \
                else r["candidate"]
            self.assertLess(len(body), len(r["reference"]))

    def test_candidate_is_a_prefix_of_the_reference(self):
        """A truncation, not a rewrite. If this fails we are generating text."""
        for r in build_trunc(self._posts(), n=10):
            body = r["candidate"].split(": ", 1)[-1] if r["candidate"].startswith("RT @") \
                else r["candidate"]
            self.assertTrue(r["reference"].startswith(body), body[:40])

    def test_keeps_enough_to_still_assert_something(self):
        """MIN_KEEP was 0.45 and cut 'Three people charged with threatening judge,
        witnesses in Nolan Wells case' down to 'Three people charged with threatening',
        which is a fragment rather than a truncated claim."""
        self.assertGreaterEqual(MIN_KEEP, 0.55)
        for r in build_trunc(self._posts(), n=10):
            self.assertGreaterEqual(len(r["candidate"]), 0.4 * len(r["reference"]))

    def test_marked_structural(self):
        self.assertTrue(all(r["confidence"] == "structural"
                            for r in build_trunc(self._posts(), n=5)))

    def test_deterministic(self):
        a = [r["candidate"] for r in build_trunc(self._posts(), n=8, seed=3)]
        b = [r["candidate"] for r in build_trunc(self._posts(), n=8, seed=3)]
        self.assertEqual(a, b)

    def test_some_carry_a_retweet_prefix(self):
        """RT truncation is the real-world shape; the prefix is surface noise the
        model must learn to ignore rather than treat as evidence."""
        rows = build_trunc(self._posts(60), n=60, rt_prefix_share=1.0)
        self.assertTrue(all(r["candidate"].startswith("RT @") for r in rows))


class TestHeadlineAsymmetry(unittest.TestCase):
    """Added because the first checkpoint made ptf-02 WORSE, 0.2611 -> 0.0527: a short
    title-plus-link against a long announcement, a shape truncation pairs never make."""

    def _posts(self, n=20):
        return [_post(str(i), "reuters.com",
                      f"US appeals court rejects the rule number {i} reut.rs/AB{i}",
                      title=f"US appeals court rejects the rule number {i}",
                      desc="The Trump administration had argued that the requirement "
                           "exceeded the agency's statutory authority under the act.")
                for i in range(n)]

    def test_reference_is_substantially_longer(self):
        rows = build_headline_pairs(self._posts(), n=10)
        self.assertTrue(rows)
        for r in rows:
            self.assertGreater(len(r["reference"]), 2 * len(r["candidate"]))

    def test_labelled_same_and_structural(self):
        for r in build_headline_pairs(self._posts(), n=5):
            self.assertIn(r["label"], POSITIVE_LABELS)
            self.assertEqual(r["confidence"], "structural")

    def test_uses_only_real_post_fields(self):
        """Both sides must be real published text; no fabricated URLs or prose."""
        posts = self._posts(5)
        by_uri = {p.uri: p for p in posts}
        for r in build_headline_pairs(posts, n=5):
            p = by_uri[r["source"]["a_uri"]]
            self.assertEqual(r["candidate"], p.text.strip())
            self.assertEqual(r["reference"], f"{p.title} {p.description}".strip())

    def test_skips_posts_without_a_lede(self):
        self.assertEqual(build_headline_pairs(
            [_post("1", "a.com", "headline only with no description at all")], n=5), [])


class TestCollisionNegatives(unittest.TestCase):
    """The ssi-05 failure: an acronym referring to a different entity. The fine-tune
    BROKE it, 0.034 -> 0.5415, and the labeller mislabels that shape too."""

    def _posts(self):
        out = []
        for i, day in enumerate(("2026-08-01", "2026-09-10")):
            for h in ("reuters.com", "apnews.com"):
                out.append(_post(f"{i}{h[:3]}", h,
                                 f"Zelenskyy Kyiv Patriots delivery update number {i}",
                                 day=day))
        return out

    def test_finds_pairs_that_share_entities_across_weeks(self):
        cands = build_collisions(self._posts(), n=20)
        self.assertTrue(cands)
        for c in cands:
            self.assertGreaterEqual(c.shared, COLLISION_MIN_SHARED)

    def test_enforces_the_day_gap(self):
        from datetime import date
        for c in build_collisions(self._posts(), n=20):
            gap = abs((date.fromisoformat(c.a_day) - date.fromisoformat(c.b_day)).days)
            self.assertGreaterEqual(gap, COLLISION_MIN_DAY_GAP)

    def test_never_pairs_an_outlet_with_itself(self):
        for c in build_collisions(self._posts(), n=20):
            self.assertNotEqual(c.a_handle, c.b_handle)

    def test_rows_are_incidental_not_unrelated(self):
        """incidental is the HARD negative: shares a named entity, asserts something
        else. Calling these unrelated would lose the distinction that matters."""
        rows = collisions_as_rows(build_collisions(self._posts(), n=10))
        self.assertTrue(rows)
        self.assertTrue(all(r["label"] == "incidental" for r in rows))
        self.assertTrue(all(r["confidence"] == "structural" for r in rows))

    def test_requires_more_shared_tokens_than_random_negatives(self):
        """Random negatives allow at most 1 shared rare token; collisions REQUIRE 2+.
        That inversion is the whole point: these are meant to be hard."""
        from mine.negatives import MAX_SHARED_RARE
        self.assertGreater(COLLISION_MIN_SHARED, MAX_SHARED_RARE)

    def test_same_day_pairs_are_excluded(self):
        same_day = [_post("1", "a.com", "Zelenskyy Kyiv Patriots delivery update"),
                    _post("2", "b.com", "Zelenskyy Kyiv Patriots delivery arrives")]
        self.assertEqual(build_collisions(same_day, n=10), [])


class TestSplit(unittest.TestCase):
    """21% of posts appear in more than one pair and one appears in 14, so a random
    row split would put the same text on both sides and inflate validation."""

    def _rows(self):
        rows = []
        for d in range(1, 21):
            for i in range(5):
                rows.append({
                    "id": f"r{d}-{i}", "reference": f"claim {d} {i}",
                    "candidate": f"other {d} {i}", "label": "same_paraphrase",
                    "confidence": "machine",
                    "source": {"kind": "bluesky-mined", "a_lang": "en", "b_lang": "en",
                               "a_day": f"2026-09-{d:02d}", "b_day": f"2026-09-{d:02d}",
                               "a_uri": f"u{d}-{i}a", "b_uri": f"u{d}-{i}b",
                               "jaccard": 0.1, "cross_lingual": False},
                })
        return rows

    def test_no_day_appears_in_both_splits(self):
        tr, va, _ = split_by_day(self._rows(), val_share=0.2, seed=0)
        tr_days = {r["source"]["a_day"] for r in tr}
        va_days = {r["source"]["a_day"] for r in va}
        self.assertFalse(tr_days & va_days)

    def test_no_post_uri_crosses_the_boundary(self):
        tr, va, _ = split_by_day(self._rows(), val_share=0.2, seed=0)
        tr_uris = {u for r in tr for u in (r["source"]["a_uri"], r["source"]["b_uri"])}
        va_uris = {u for r in va for u in (r["source"]["a_uri"], r["source"]["b_uri"])}
        self.assertFalse(tr_uris & va_uris)

    def test_leakage_is_reported_not_silently_allowed(self):
        rows = self._rows()
        # A pair whose two posts sit on different days can straddle the boundary.
        rows.append({**rows[0], "id": "straddle",
                     "source": {**rows[0]["source"], "a_day": "2026-09-01",
                                "b_day": "2026-09-20", "b_uri": "u20-0a"}})
        _, _, rep = split_by_day(rows, val_share=0.2, seed=0)
        self.assertIn("val_dropped_for_leakage", rep)

    def test_split_is_deterministic(self):
        a = split_by_day(self._rows(), seed=5)[1]
        b = split_by_day(self._rows(), seed=5)[1]
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])

    def test_both_splits_are_non_empty(self):
        tr, va, _ = split_by_day(self._rows(), val_share=0.2, seed=0)
        self.assertTrue(tr and va)


class TestClassWeights(unittest.TestCase):
    def test_rare_class_gets_more_weight(self):
        rows = ([{"label": "unrelated"}] * 100) + ([{"label": "same_verbatim"}] * 5)
        w = class_weights(rows)
        self.assertGreater(w[LABELS.index("same_verbatim")],
                           w[LABELS.index("unrelated")])

    def test_cap_prevents_a_rare_class_dominating(self):
        """Uncapped, same_verbatim's inverse frequency would swamp the loss and the
        model would learn to shout that class."""
        rows = ([{"label": "unrelated"}] * 10000) + ([{"label": "same_verbatim"}] * 1)
        self.assertLessEqual(max(class_weights(rows, cap=8.0)), 8.0)

    def test_one_weight_per_label_in_order(self):
        w = class_weights([{"label": "unrelated"}])
        self.assertEqual(len(w), len(LABELS))


class TestExamples(unittest.TestCase):
    def test_binary_target_matches_the_positive_set(self):
        rows = [{"label": l, "reference": "a", "candidate": "b"} for l in LABELS]
        for ex, label in zip(to_examples(rows), LABELS):
            self.assertEqual(ex["is_same"], 1.0 if label in POSITIVE_LABELS else 0.0)

    def test_label_index_is_the_pinned_order(self):
        rows = [{"label": l, "reference": "a", "candidate": "b"} for l in LABELS]
        self.assertEqual([e["label"] for e in to_examples(rows)],
                         list(range(len(LABELS))))


class TestRobustSeparation(unittest.TestCase):
    """A checkpoint scoring AUC 0.987 reported a raw margin of -0.95, worse than the
    untrained baseline, because 2 of 1,008 rows sat on the wrong side."""

    def test_one_outlier_destroys_the_raw_margin(self):
        pos = [0.9] * 99 + [0.01]
        neg = [0.1] * 99 + [0.99]
        self.assertLess(separation(pos, neg)[0], 0)

    def test_robust_margin_survives_that_outlier(self):
        pos = [0.9] * 99 + [0.01]
        neg = [0.1] * 99 + [0.99]
        self.assertGreater(robust_separation(pos, neg), 0)

    def test_robust_margin_still_negative_when_truly_overlapping(self):
        pos = [0.4 + 0.002 * i for i in range(100)]
        neg = [0.4 + 0.002 * i for i in range(100)]
        self.assertLessEqual(robust_separation(pos, neg), 0.05)

    def test_needs_both_sides(self):
        self.assertIsNone(robust_separation([0.9], []))


class TestRealDataLoads(unittest.TestCase):
    def test_english_filter_and_sources(self):
        rows = load_rows(english_only=True)
        if not rows:
            self.skipTest("mine/out not populated")
        for r in rows[:200]:
            self.assertEqual(r["source"]["a_lang"], "en")
            self.assertEqual(r["source"]["b_lang"], "en")

    def test_no_self_pairs(self):
        rows = load_rows()
        if not rows:
            self.skipTest("mine/out not populated")
        self.assertFalse([r for r in rows if r["reference"] == r["candidate"]])

    def test_every_class_present(self):
        rows = load_rows()
        if not rows:
            self.skipTest("mine/out not populated")
        self.assertEqual({r["label"] for r in rows}, set(LABELS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
