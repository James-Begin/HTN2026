"""Integration tests against the live APIs.

These cost money. They are skipped unless credentials are present, and the
expensive ones additionally require CLAIMTRACE_SLOW=1.

    python -m unittest tests.test_integration -v          # cheap only, ~$0.15
    CLAIMTRACE_SLOW=1 python -m unittest tests.test_integration -v   # all, ~$1.20

Assertions come from tests/fixtures/cases.json, which records what was actually
measured rather than what we hope happens.
"""
import json
import os
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claimtrace import config as C                          # noqa: E402
from claimtrace.baseten import CrossEncoder, HostedLLM      # noqa: E402
from claimtrace.pipeline import anchor_query, extract, route, shape  # noqa: E402
from claimtrace.xapi import XClient, now_safe               # noqa: E402

FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "cases.json").read_text())

HAVE_X = bool(C.X_BEARER)
HAVE_BT = bool(C.BASETEN_API_KEY)
SLOW = os.environ.get("CLAIMTRACE_SLOW") == "1"

needs_x = unittest.skipUnless(HAVE_X, "X_BEARER not set")
needs_bt = unittest.skipUnless(HAVE_BT, "BASETEN_API_KEY not set")
slow = unittest.skipUnless(SLOW, "set CLAIMTRACE_SLOW=1 to run (costs ~$1)")


def case(section, name):
    for c in FIXTURES[section]:
        if c.get("name") == name:
            return c
    raise KeyError(f"{section}/{name}")


# ---------------------------------------------------------------- X API shape
@needs_x
class TestXApiContract(unittest.TestCase):
    """Pin the API behaviours the whole design rests on. Cheap."""

    @classmethod
    def setUpClass(cls):
        cls.x = XClient(C.X_BEARER, post_budget=80)

    def test_miss_costs_nothing(self):
        """The economics of bisection depend entirely on this."""
        before = self.x.posts_read
        hit = self.x.exists_before('"zqxjkvwmb nonexistent phrase 91744"', now_safe())
        self.assertFalse(hit)
        self.assertEqual(self.x.posts_read, before, "a miss must bill zero posts")

    def test_max_results_below_ten_is_clamped_not_sent(self):
        """The API rejects 1 outright, so the client must clamp."""
        rows, _ = self.x.search('"just setting up my twttr"',
                                C.ARCHIVE_FLOOR,
                                datetime(2007, 1, 1, tzinfo=timezone.utc),
                                max_results=1)
        self.assertGreater(len(rows), 0)

    def test_future_end_time_is_rejected(self):
        future = datetime.now(timezone.utc) + timedelta(days=400)
        with self.assertRaises(RuntimeError):
            self.x.search("covfefe", C.ARCHIVE_FLOOR, future)

    def test_counts_total_is_per_page_not_per_range(self):
        """Measured. If this ever changes, a 13-request bisect becomes possible."""
        end = now_safe()
        buckets, token = self.x.counts("hackathon", end - timedelta(days=90), end)
        self.assertIsNotNone(token, "a 90-day range must paginate")
        self.assertLessEqual(len(buckets), C.COUNTS_PAGE_DAYS)

    def test_counts_pages_are_newest_first(self):
        end = now_safe()
        buckets, _ = self.x.counts("hackathon", end - timedelta(days=90), end)
        newest = max(b["start"] for b in buckets)
        self.assertGreater(newest[:10], (end - timedelta(days=40)).strftime("%Y-%m-%d"),
                           "first page should be the most recent 31 days")

    def test_full_archive_reaches_2006(self):
        rows, _ = self.x.search('"just setting up my twttr"',
                                C.ARCHIVE_FLOOR,
                                datetime(2007, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(rows)
        self.assertTrue(all(r["created_at"].startswith("2006") for r in rows))

    def test_web_search_operator_names_are_rejected(self):
        """min_faves is the web name; the API wants min_likes."""
        with self.assertRaises(RuntimeError):
            self.x.search("covfefe min_faves:100", C.ARCHIVE_FLOOR, now_safe())

    def test_api_operator_names_are_accepted(self):
        rows, _ = self.x.search(f"covfefe {C.OP_MIN_LIKES}:100",
                                C.ARCHIVE_FLOOR, now_safe())
        self.assertTrue(all(r["public_metrics"]["like_count"] >= 100 for r in rows))

    def test_budget_guard_is_enforced_against_live_calls(self):
        from claimtrace.xapi import BudgetExceeded
        tiny = XClient(C.X_BEARER, post_budget=10)
        tiny.search("covfefe", C.ARCHIVE_FLOOR, now_safe())     # 10 posts
        with self.assertRaises(BudgetExceeded):
            tiny.search("covfefe", C.ARCHIVE_FLOOR, now_safe())


# ------------------------------------------------------------------- the bisect
@needs_x
@slow
class TestBisectGroundTruth(unittest.TestCase):
    """The gold test: does it find the first tweet ever posted."""

    def test_finds_tweet_20_exactly(self):
        c = case("ground_truth_earliest", "first_tweet_ever")
        x = XClient(C.X_BEARER, post_budget=420)
        first, meta = x.earliest(c["query"])
        self.assertIsNotNone(first)
        self.assertEqual(first["id"], c["expect_earliest_id"])
        self.assertTrue(first["created_at"].startswith(c["expect_earliest_date"]))
        self.assertLess(meta["probes"], 40, "bisect should be O(log n), not a scan")

    def test_deleted_root_lands_close_but_does_not_overclaim(self):
        c = case("ground_truth_earliest", "covfefe_deleted_root")
        x = XClient(C.X_BEARER, post_budget=420)
        first, _ = x.earliest(c["query"])
        self.assertIsNotNone(first)
        self.assertTrue(first["created_at"].startswith(c["expect_earliest_date"]))
        # The true origin is deleted, so what we find must be strictly after it.
        self.assertGreater(first["created_at"], c["expect_earliest_after"],
                           "cannot find a deleted post; earliest surviving must be later")


# ----------------------------------------------------------------- the router
@needs_x
class TestRouterOnLiveData(unittest.TestCase):
    def test_routing_is_a_function_of_pre_spike_volume(self):
        """Routing is TIME-RELATIVE, so assert the rule, not a recorded label.

        The same claim measured VERIFY at 2 hours old (pre-spike 1) and LINEAGE a
        day later (pre-spike 21), because yesterday's posts became history. Any
        fixture holding an absolute route for a live claim will go stale.
        """
        c = case("routing", "recent_spike_verify")
        x = XClient(C.X_BEARER, post_budget=20)
        sh = shape(x, c["query"])
        expected = ("ABSTAIN" if sh["total_30d"] == 0
                    else "LINEAGE" if sh["pre_spike_total"] >= C.MIN_PRE_SPIKE_FOR_LINEAGE
                    else "VERIFY")
        self.assertEqual(route(sh), expected,
                         f"pre_spike={sh['pre_spike_total']} total={sh['total_30d']}")

    def test_same_event_two_queries_two_routes(self):
        """The most interesting property: mode depends on the QUERY, not the event.

        The essay title has no pre-spike history and is a corroboration case.
        The phrase within it has a clear ramp and is a lineage case. Both correct.
        """
        x = XClient(C.X_BEARER, post_budget=30)
        title = case("routing", "essay_title_has_no_history")
        phrase = case("routing", "phrase_has_history_lineage")

        sh_title = shape(x, title["query"])
        self.assertEqual(route(sh_title), "VERIFY")
        self.assertLess(sh_title["pre_spike_total"], C.MIN_PRE_SPIKE_FOR_LINEAGE)

        sh_phrase = shape(x, phrase["query"])
        self.assertEqual(route(sh_phrase), "LINEAGE")
        self.assertGreater(sh_phrase["pre_spike_total"], 1000)

        # Both describe the same real-world event.
        self.assertEqual(sh_title["peak_day"][:7], sh_phrase["peak_day"][:7])

    def test_nonsense_query_abstains_for_one_cent(self):
        x = XClient(C.X_BEARER, post_budget=20)
        sh = shape(x, '"zqxjkvwmb nonexistent phrase 91744"')
        self.assertEqual(route(sh), "ABSTAIN")
        self.assertEqual(x.posts_read, 0, "abstain must not read any posts")


# ------------------------------------------------------------ semantic gating
@needs_bt
class TestCrossEncoder(unittest.TestCase):
    """Documents both what off-the-shelf weights get right and what they miss."""

    @classmethod
    def setUpClass(cls):
        cls.xe = CrossEncoder(C.BASETEN_API_KEY)
        try:
            cls.xe.score("warmup", ["warmup"])
        except Exception as e:
            raise unittest.SkipTest(f"cross-encoder unavailable (deactivated?): {e}")

    def test_rejects_cross_lingual_collision(self):
        c = case("ambiguity_collisions", "ssi_korean_honorific")
        ref = FIXTURES["paraphrase_recall"][0]["reference"]
        score = self.xe.score(ref, [c["collision_text"]])[0]
        self.assertLess(score, c["expect_score_below"],
                        f"Korean honorific scored {score}, should be near zero")

    def test_accepts_verbatim_and_retweet(self):
        ref = FIXTURES["paraphrase_recall"][0]["reference"]
        scores = self.xe.score(ref, [ref, f"RT @someone: {ref[:80]}"])
        self.assertGreater(scores[0], 0.95)
        self.assertGreater(scores[1], 0.5)

    def test_paraphrase_gap_is_still_open(self):
        """This test EXISTS TO FAIL once the fine-tune lands. It records the gap."""
        c = case("paraphrase_recall", "ssi_restated")
        score = self.xe.score(c["reference"], [c["paraphrase"]])[0]
        self.assertLess(score, c["expect_finetuned_above"],
                        "paraphrase now scores above threshold -> update the fixture, "
                        "the fine-tune worked")
        self.assertAlmostEqual(score, c["offtheshelf_score"], delta=0.08,
                               msg="off-the-shelf score drifted from the recorded baseline")


# ------------------------------------------------------------------ extraction
@needs_bt
class TestExtraction(unittest.TestCase):
    def test_produces_a_usable_anchor_and_valid_query(self):
        llm = HostedLLM(C.BASETEN_API_KEY)
        text = FIXTURES["paraphrase_recall"][0]["reference"]
        plan = extract(llm, text)
        self.assertTrue(plan["anchor"])
        q = anchor_query(plan)
        # Whatever the model returned, the query must be syntactically safe.
        self.assertEqual(q.count('"') % 2, 0)
        self.assertNotIn('""', q)
        self.assertNotIn(",", q)
        self.assertNotIn(" AND ", q)

    def test_anchor_appears_in_the_source_text(self):
        llm = HostedLLM(C.BASETEN_API_KEY)
        text = FIXTURES["paraphrase_recall"][0]["reference"]
        plan = extract(llm, text)
        self.assertIn(plan["anchor"].lower().strip('"'), text.lower(),
                      "anchor must be verbatim from the claim, not invented")

    @needs_x
    def test_generated_query_actually_executes(self):
        """The end-to-end contract: model output must survive the API grammar."""
        llm = HostedLLM(C.BASETEN_API_KEY)
        x = XClient(C.X_BEARER, post_budget=20)
        plan = extract(llm, FIXTURES["paraphrase_recall"][0]["reference"])
        sh = shape(x, anchor_query(plan))   # raises if the grammar rejects it
        self.assertIsInstance(sh["total_30d"], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
