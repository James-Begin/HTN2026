"""Unit tests. No network. Every case here is a regression we actually hit.

    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claimtrace import config as C                      # noqa: E402
from claimtrace.pipeline import anchor_query, route, shape, _phrase  # noqa: E402
from claimtrace.xapi import (BudgetExceeded, XClient, is_handle,     # noqa: E402
                             iso, now_safe, sanitize_query)


class TestSanitizeQuery(unittest.TestCase):
    """X's grammar is narrow and LLM output violates it in specific ways."""

    def test_strips_explicit_AND(self):
        # X uses IMPLICIT and. The literal token is a hard 400.
        self.assertEqual(sanitize_query('"a b" AND "c d"'), '"a b" "c d"')
        self.assertEqual(sanitize_query('x and y'), 'x y')
        self.assertEqual(sanitize_query('x && y'), 'x y')

    def test_preserves_OR(self):
        # OR *is* a valid operator; do not strip it.
        self.assertIn("OR", sanitize_query('cats OR dogs'))

    def test_drops_commas_that_break_the_parser(self):
        # "no viable alternative at character ','"
        self.assertNotIn(",", sanitize_query("SSI, delayed, breached"))

    def test_drops_parenthetical_asides(self):
        out = sanitize_query("SSI (Supplemental Security Income) delayed")
        self.assertNotIn("(", out)
        self.assertNotIn("Supplemental", out)

    def test_balances_quotes(self):
        # An odd number of quotes trips "Phrases cannot be empty".
        self.assertEqual(sanitize_query('"unclosed phrase').count('"') % 2, 0)

    def test_truncation_never_leaves_odd_quotes(self):
        long = " ".join(f'"phrase {i}"' for i in range(20))
        self.assertEqual(sanitize_query(long).count('"') % 2, 0)

    def test_strips_stray_operator_chars(self):
        self.assertEqual(sanitize_query("- foo :"), "foo")

    def test_empty_and_operator_only_input(self):
        self.assertEqual(sanitize_query(""), "")
        self.assertEqual(sanitize_query(None or ""), "")
        self.assertEqual(sanitize_query("OR"), "")

    def test_respects_word_cap(self):
        self.assertLessEqual(len(sanitize_query(" ".join(["w"] * 40)).split()), 12)

    def test_keeps_useful_syntax(self):
        out = sanitize_query('from:jack #hashtag @mention')
        for tok in ("from:jack", "#hashtag", "@mention"):
            self.assertIn(tok, out)


class TestIsHandle(unittest.TestCase):
    """`from:` needs a screen name. The model often returns a description."""

    def test_accepts_real_handles(self):
        for h in ("jack", "@jack", "iruletheworldmo", "a_b_1"):
            self.assertTrue(is_handle(h), h)

    def test_rejects_prose(self):
        for bad in ("security breach impact on SSI systems", "", None,
                    "a" * 16, "has spaces", "has-dash"):
            self.assertFalse(is_handle(bad or ""), repr(bad))


class TestAnchorQuery(unittest.TestCase):
    def test_wraps_anchor_as_phrase(self):
        q = anchor_query({"anchor": "catastrophic security incident", "negatives": []})
        self.assertEqual(q, '"catastrophic security incident"')

    def test_prequoted_negatives_do_not_nest(self):
        # Real model output. Naive wrapping made -""SSI" income" -> empty phrase.
        q = anchor_query({"anchor": "ssi are delayed",
                          "negatives": ['"SSI" supplemental security income']})
        self.assertNotIn('""', q)
        self.assertEqual(q.count('"') % 2, 0)

    def test_negative_cannot_swallow_the_anchor(self):
        q = anchor_query({"anchor": "pace the frontier",
                          "negatives": ["pace the frontier"]})
        self.assertNotIn("-", q)

    def test_negatives_can_be_disabled_for_fallback(self):
        plan = {"anchor": "a b c", "negatives": ["x y"]}
        self.assertNotIn("-", anchor_query(plan, with_negatives=False))

    def test_missing_anchor_raises(self):
        with self.assertRaises(ValueError):
            anchor_query({"anchor": "", "negatives": []})

    def test_phrase_helper_returns_empty_on_junk(self):
        self.assertEqual(_phrase("(((  )))"), "")


class TestRouter(unittest.TestCase):
    @staticmethod
    def curve(vals):
        base = datetime(2026, 8, 15, tzinfo=timezone.utc)
        return [((base + timedelta(days=i)).strftime("%Y-%m-%d"), v)
                for i, v in enumerate(vals)]

    def test_zero_volume_abstains(self):
        self.assertEqual(route({"total_30d": 0, "spike_is_recent": False, "spike_ratio": 0}),
                         "ABSTAIN")

    def test_recent_spike_routes_to_verify(self):
        sh = {"total_30d": 500, "spike_is_recent": True, "spike_ratio": 50.0}
        self.assertEqual(route(sh), "VERIFY")

    def test_low_volume_routes_to_verify(self):
        sh = {"total_30d": 5, "spike_is_recent": False, "spike_ratio": 1.0}
        self.assertEqual(route(sh), "VERIFY")

    def test_history_plus_spike_routes_to_lineage(self):
        sh = {"total_30d": 20000, "spike_is_recent": False, "spike_ratio": 40.0}
        self.assertEqual(route(sh), "LINEAGE")

    def test_shape_math_on_a_flat_then_spike_curve(self):
        class FakeX:
            def daily_curve(self, q, days=30):
                return TestRouter.curve([0] * 28 + [16410, 19682])
        sh = shape(FakeX(), "q")
        self.assertEqual(sh["total_30d"], 36092)
        self.assertEqual(sh["peak"], 19682)
        self.assertTrue(sh["spike_is_recent"])
        self.assertGreater(sh["spike_ratio"], C.SPIKE_RATIO)

    def test_history_before_spike_forces_lineage(self):
        """Regression: a recent huge spike WITH prior history is a lineage case."""
        sh = {"total_30d": 16679, "spike_is_recent": True, "spike_ratio": 9571.0,
              "pre_spike_total": 7108}
        self.assertEqual(route(sh), "LINEAGE")

    def test_spike_from_nothing_is_verify(self):
        sh = {"total_30d": 31, "spike_is_recent": True, "spike_ratio": 20.0,
              "pre_spike_total": 0}
        self.assertEqual(route(sh), "VERIFY")

    def test_shape_computes_pre_spike_volume(self):
        class FakeX:
            def daily_curve(self, q, days=30):
                return TestRouter.curve([0] * 25 + [14, 37, 76, 9571, 5000])
        sh = shape(FakeX(), "q")
        self.assertEqual(sh["pre_spike_total"], 127)
        self.assertEqual(sh["peak"], 9571)

    def test_shape_on_all_zero_curve(self):
        class FakeX:
            def daily_curve(self, q, days=30):
                return TestRouter.curve([0] * 30)
        sh = shape(FakeX(), "q")
        self.assertEqual(sh["total_30d"], 0)
        self.assertEqual(route(sh), "ABSTAIN")


class TestBudgetGuard(unittest.TestCase):
    """The unbounded-pagination bug cost $8.50. This is the wall against it."""

    def setUp(self):
        self.x = XClient("fake-bearer", post_budget=25)

    def test_guard_blocks_before_the_call(self):
        self.x.posts_read = 20
        with self.assertRaises(BudgetExceeded):
            self.x._guard(10)

    def test_guard_allows_within_budget(self):
        self.x.posts_read = 10
        self.x._guard(10)   # must not raise

    def test_spend_arithmetic(self):
        self.x.posts_read, self.x.counts_calls = 100, 5
        expected = 100 * C.COST_PER_POST_READ + 5 * C.COST_PER_COUNTS_ALL
        self.assertAlmostEqual(self.x.spend, expected)

    def test_empty_bearer_rejected(self):
        with self.assertRaises(ValueError):
            XClient("")


class TestTimeHelpers(unittest.TestCase):
    def test_end_time_is_never_now(self):
        # Passing the present moment returns HTTP 400.
        self.assertLess(now_safe(), datetime.now(timezone.utc))

    def test_iso_format_is_what_the_api_wants(self):
        self.assertEqual(iso(datetime(2006, 3, 21, 20, 50, 14, tzinfo=timezone.utc)),
                         "2006-03-21T20:50:14Z")

    def test_archive_floor_matches_first_tweet(self):
        self.assertEqual(C.ARCHIVE_FLOOR.year, 2006)
        self.assertEqual(C.ARCHIVE_FLOOR.month, 3)


class TestConfigInvariants(unittest.TestCase):
    """Guard the constants that encode API limits."""

    def test_max_results_floor_is_ten(self):
        # The API rejects 1 with an explicit "not between 10 and 500".
        self.assertEqual(C.SEARCH_MIN_RESULTS, 10)
        self.assertEqual(C.SEARCH_MAX_RESULTS, 500)

    def test_engagement_operator_names(self):
        # min_faves / min_retweets are web-search only and return 400.
        self.assertEqual(C.OP_MIN_LIKES, "min_likes")
        self.assertEqual(C.OP_MIN_REPOSTS, "min_reposts")

    def test_reasoning_effort_is_disabled_by_default(self):
        # Default reasoning burns 68-89 tokens on a one-word answer.
        self.assertEqual(C.REASONING_EFFORT, "none")

    def test_max_tokens_floor_leaves_headroom(self):
        # Too tight and content comes back None with finish_reason=length.
        self.assertGreaterEqual(C.MIN_MAX_TOKENS, 32)

    def test_hosted_concurrency_is_conservative(self):
        # Measured: 8 is healthy, 64 collapses to 1.4 req/s.
        self.assertLessEqual(C.HOSTED_SAFE_CONCURRENCY, 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
