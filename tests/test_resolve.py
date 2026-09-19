"""Tests for Snowflake decoding and the four-state resolver.

The resolver hits a free, unauthenticated endpoint, so these cost nothing and
need no credentials. Assertions come from tests/fixtures/corpus.json, which was
built by an independent verification sweep of 45 tweets with zero fabrications.
"""
import json
import pathlib
import sys
import os
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claimtrace.resolve import (DELETED, LIVE, NONEXISTENT, PROTECTED,  # noqa: E402
                                resolve, tweet_id_from_url)
from claimtrace.xapi import id_is_plausible_for, id_to_time            # noqa: E402

CORPUS = json.loads((pathlib.Path(__file__).parent / "fixtures" / "corpus.json").read_text())


def edge(name):
    for c in CORPUS["killer_edge_cases"]:
        if c["name"] == name:
            return c
    raise KeyError(name)


class TestSnowflake(unittest.TestCase):
    """A tweet id carries its own timestamp. Free, offline, works on deleted posts."""

    def test_decodes_the_deleted_covfefe_original(self):
        # The content is gone but the id still tells us exactly when it was posted.
        t = id_to_time("869766994899468288")
        self.assertEqual(t.strftime("%Y-%m-%dT%H:%M:%S"), "2017-05-31T04:06:25")

    def test_decodes_the_most_liked_tweet(self):
        t = id_to_time("1299530165463199747")
        self.assertEqual(t.strftime("%Y-%m-%dT%H:%M:%S"), "2020-08-29T02:11:50")

    def test_pre_snowflake_ids_raise_rather_than_lie(self):
        # id 20 predates Snowflake entirely; a decoded value would be nonsense.
        for old in ("20", "21", "51", "922321981", "223115412"):
            with self.assertRaises(ValueError, msg=old):
                id_to_time(old)

    def test_plausibility_check_accepts_truth(self):
        when = datetime(2017, 5, 31, 4, 6, 25, tzinfo=timezone.utc)
        self.assertTrue(id_is_plausible_for("869766994899468288", when))

    def test_plausibility_check_rejects_a_mismatched_id(self):
        wrong = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(id_is_plausible_for("869766994899468288", wrong))

    def test_plausibility_never_fails_pre_snowflake(self):
        # Cannot be checked, so must not be reported as false.
        self.assertTrue(id_is_plausible_for("20", datetime(1999, 1, 1, tzinfo=timezone.utc)))

    def test_ids_are_monotonic_in_time(self):
        a = id_to_time("869766994899468288")   # 2017
        b = id_to_time("1299530165463199747")  # 2020
        self.assertLess(a, b)


class TestUrlParsing(unittest.TestCase):
    def test_extracts_id_from_various_url_shapes(self):
        for url in ("https://x.com/jack/status/20",
                    "https://twitter.com/jack/status/20",
                    "https://x.com/jack/status/20?s=20&t=abc",
                    "https://x.com/jack/status/20/"):
            self.assertEqual(tweet_id_from_url(url), "20")

    def test_rejects_non_numeric(self):
        with self.assertRaises(ValueError):
            resolve("https://x.com/jack/status/notanid")


class TestFourStates(unittest.TestCase):
    """Live network, but free and unauthenticated."""

    def test_live_tweet(self):
        r = resolve("20")
        self.assertEqual(r.state, LIVE)
        self.assertEqual(r.text, "just setting up my twttr")
        self.assertEqual(r.handle, "jack")
        self.assertTrue(r.recoverable_text)
        self.assertTrue(r.existed)

    def test_deleted_is_a_positive_finding_not_a_failure(self):
        """The point of the whole resolver: DELETED != never existed."""
        r = resolve("869766994899468288")
        self.assertEqual(r.state, DELETED)
        self.assertTrue(r.existed, "a deleted post provably existed")
        self.assertFalse(r.recoverable_text)
        self.assertIn("deleted", r.tombstone.lower())
        # And we still know exactly when, from the id alone.
        self.assertEqual(r.created_at.strftime("%Y-%m-%d %H:%M"), "2017-05-31 04:06")

    def test_protected_is_distinct_from_deleted(self):
        r = resolve("223115412")
        self.assertEqual(r.state, PROTECTED)
        self.assertTrue(r.existed)

    def test_fabricated_id_is_nonexistent(self):
        r = resolve("999999999999999999999")
        self.assertEqual(r.state, NONEXISTENT)
        self.assertFalse(r.existed)


class TestKillerEdgeCases(unittest.TestCase):
    def test_most_liked_tweet_in_history_has_no_prose(self):
        """A text-only pipeline scores the biggest tweet ever as a null document."""
        c = edge("empty_text_most_liked")
        r = resolve(c["id"])
        self.assertEqual(r.state, LIVE)
        self.assertTrue(r.text.startswith("https://t.co/"),
                        "text should be nothing but a link")
        self.assertGreaterEqual(len(r.media), 1, "the claim lives in the media")
        # The guard a real pipeline needs:
        prose = r.text.split("https://")[0].strip()
        self.assertEqual(prose, "", "no prose at all -> must route to the image path")

    def test_handle_drift_means_identity_must_use_the_id(self):
        c = edge("handle_drift")
        r = resolve(c["id"])
        self.assertEqual(r.state, LIVE)
        self.assertEqual(r.handle, c["current_handle"])
        self.assertNotEqual(r.handle, c["old_handle"],
                            "the handle in every published citation is now wrong")
        self.assertEqual(r.author_id, c["author_id"],
                         "the immutable id is the only stable identity")

    def test_deleted_root_and_live_followup_are_not_confusable(self):
        """The exact failure mode this tool exists to catch."""
        c = edge("deleted_root_vs_live_followup")
        root = resolve(c["deleted_id"])
        survivor = resolve(c["live_id"])
        self.assertEqual(root.state, DELETED)
        self.assertEqual(survivor.state, LIVE)
        # Adjacent in time and topic, so retrieval will offer the survivor.
        self.assertLess(root.created_at, survivor.created_at)
        gap_h = (survivor.created_at - root.created_at).total_seconds() / 3600
        self.assertAlmostEqual(gap_h, c["gap_hours"], delta=0.5)
        # A correct system reports "root existed and is gone", not the survivor.
        self.assertTrue(root.existed and not root.recoverable_text)


class TestRetrievalHostileCorpus(unittest.TestCase):
    """Posts that keyword retrieval structurally cannot find."""

    def test_single_word_posts_resolve_but_are_unsearchable(self):
        for entry in CORPUS["retrieval_hostile"]:
            if len(entry["text"].split()) <= 1:
                r = resolve(entry["id"])
                self.assertEqual(r.state, LIVE, entry["id"])
                self.assertLessEqual(len(r.text.split()), 1)

    def test_unicode_lookalike_is_not_ascii(self):
        r = resolve("1683301504248061952")
        self.assertEqual(r.state, LIVE)
        self.assertNotEqual(r.text.strip(), "X", "must not be ASCII X")
        self.assertEqual(r.text.strip(), "\U0001D54F")

    def test_typos_are_preserved_and_are_better_fingerprints(self):
        r = resolve("247222360309121024")
        self.assertEqual(r.state, LIVE)
        self.assertIn("scraeming", r.text, "the typo is the fingerprint")


if __name__ == "__main__":
    unittest.main(verbosity=2)
