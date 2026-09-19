"""Tests for the hybrid labeller. No network: the model is faked.

The composition here was arrived at by measurement, not design, so the tests pin the
measured facts as much as the code paths.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mine.label2 import (META_SYSTEM, OUTLET_HANDLES, SAME_SYSTEM, _is_verbatim,
                         b_is_outlet, label_hybrid)
from mine.outlets import HANDLES
from mine.relabel import plan


class FakeLLM:
    """Answers by which system prompt it is handed, and counts the calls."""

    def __init__(self, response=False, same=True, five_way="same_paraphrase"):
        self.response = response
        self.same = same
        self.five_way = five_way
        self.asked = []

    def json_call(self, system, user, max_tokens=None):
        if system is META_SYSTEM:
            self.asked.append("meta")
            return {"response": self.response, "confidence": 0.95, "reason": "r"}
        if system is SAME_SYSTEM:
            self.asked.append("same")
            return {"same": self.same, "confidence": 0.9, "reason": "s"}
        self.asked.append("5way")
        return {"label": self.five_way, "confidence": 0.9, "reason": "f"}


REPLY = {"b_handle": "someone.bsky.social"}
OUTLET = {"b_handle": "reuters.com"}


class TestOutletGate(unittest.TestCase):
    """Measured on 180 reference pairs carrying provenance: `meta` is 20 of 23 among
    replies and 1 of 157 among newsroom posts. Running the meta question on outlet
    pairs is what wrecked the first cascade, dropping same_paraphrase 81% -> 74% and
    same_verbatim 100% -> 69%."""

    def test_curated_handles_recognised(self):
        self.assertTrue(b_is_outlet({"b_handle": "reuters.com"}))
        self.assertTrue(b_is_outlet({"b_handle": "lemonde.fr"}))

    def test_random_reply_handle_is_not_an_outlet(self):
        self.assertFalse(b_is_outlet({"b_handle": "someone.bsky.social"}))

    def test_missing_provenance_is_not_an_outlet(self):
        self.assertFalse(b_is_outlet({}))
        self.assertFalse(b_is_outlet(None))

    def test_gate_covers_every_curated_handle(self):
        self.assertEqual(OUTLET_HANDLES, frozenset(HANDLES))

    def test_outlet_pair_never_asks_the_meta_question(self):
        llm = FakeLLM(response=True)
        label_hybrid(llm, "x", "A claim", "B claim", OUTLET)
        self.assertNotIn("meta", llm.asked)

    def test_reply_pair_does_ask_it(self):
        llm = FakeLLM(response=False)
        label_hybrid(llm, "x", "A claim", "B claim", REPLY)
        self.assertIn("meta", llm.asked)


class TestHybridRouting(unittest.TestCase):
    def test_detector_firing_wins(self):
        llm = FakeLLM(response=True, five_way="same_paraphrase")
        r = label_hybrid(llm, "x", "A", "B", REPLY)
        self.assertEqual(r.label, "meta")
        self.assertEqual(r.stage, "meta-detector")
        self.assertNotIn("5way", llm.asked, "no need to ask further once meta fires")

    def test_detector_silent_falls_through_to_five_way(self):
        llm = FakeLLM(response=False, five_way="incidental")
        r = label_hybrid(llm, "x", "A", "B", REPLY)
        self.assertEqual(r.label, "incidental")
        self.assertEqual(r.stage, "5way")

    def test_five_way_meta_on_an_outlet_pair_is_overruled(self):
        """95 outlet-B training rows are labelled meta against a 1-in-157 prior."""
        llm = FakeLLM(five_way="meta", same=True)
        r = label_hybrid(llm, "x", "A claim here", "A claim here", OUTLET)
        self.assertEqual(r.stage, "meta-overruled")
        self.assertIn(r.label, ("same_verbatim", "same_paraphrase"))

    def test_overruled_to_negative_when_not_the_same(self):
        llm = FakeLLM(five_way="meta", same=False)
        r = label_hybrid(llm, "x", "senate budget vote passes today",
                         "oasis announce a reunion tour", OUTLET)
        self.assertIn(r.label, ("incidental", "unrelated"))

    def test_failure_propagates_rather_than_guessing(self):
        class Broken(FakeLLM):
            def json_call(self, system, user, max_tokens=None):
                raise RuntimeError("boom")
        r = label_hybrid(Broken(), "x", "A", "B", OUTLET)
        self.assertFalse(r.ok)


class TestVerbatimHeuristic(unittest.TestCase):
    """Stage 3 decides verbatim without a model call, because the definition is
    mechanical: identical text, a truncation, or an RT prefix."""

    def test_identical_is_verbatim(self):
        t = "Senate passes the appropriations bill after a long debate today"
        self.assertTrue(_is_verbatim(t, t))

    def test_truncation_is_verbatim(self):
        a = "Senate passes the appropriations bill after a long debate today"
        self.assertTrue(_is_verbatim(a, "Senate passes the appropriations bill after"))

    def test_rt_prefix_is_verbatim(self):
        a = "Senate passes the appropriations bill after a long debate today"
        self.assertTrue(_is_verbatim(a, f"RT @reuters: {a}"))

    def test_genuine_rewording_is_not_verbatim(self):
        self.assertFalse(_is_verbatim(
            "Senate passes the appropriations bill after a long debate today",
            "Lawmakers approved federal funding following extended argument"))

    def test_empty_is_not_verbatim(self):
        self.assertFalse(_is_verbatim("", "anything at all here"))


class TestRelabelPlan(unittest.TestCase):
    """The incremental plan exists because a full re-label is ~21,000 calls and only
    two situations can actually change: a reply where the detector fires, and an
    existing `meta` the prior contradicts."""

    def _row(self, label, handle, confidence="machine"):
        return {"reference": f"A {label} {handle}", "candidate": f"B {label} {handle}",
                "label": label, "confidence": confidence,
                "source": {"b_handle": handle}}

    def test_structural_rows_are_never_touched(self):
        rows = [self._row("unrelated", "reuters.com", confidence="structural")]
        need_meta, need_same, keep = plan(rows)
        self.assertEqual((need_meta, need_same), ([], []))
        self.assertEqual(len(keep), 1)

    def test_reply_rows_get_the_meta_question(self):
        need_meta, _, _ = plan([self._row("same_paraphrase", "someone.bsky.social")])
        self.assertEqual(len(need_meta), 1)

    def test_outlet_meta_rows_get_reassigned(self):
        _, need_same, _ = plan([self._row("meta", "reuters.com")])
        self.assertEqual(len(need_same), 1)

    def test_outlet_non_meta_rows_are_left_alone(self):
        """On these the hybrid IS the 5-way prompt, so re-asking would only add noise."""
        _, _, keep = plan([self._row("same_paraphrase", "reuters.com")])
        self.assertEqual(len(keep), 1)

    def test_plan_partitions_without_loss(self):
        rows = [self._row("meta", "reuters.com"),
                self._row("same_paraphrase", "a.bsky.social"),
                self._row("incidental", "npr.org"),
                self._row("unrelated", "reuters.com", confidence="structural")]
        need_meta, need_same, keep = plan(rows)
        self.assertEqual(len(need_meta) + len(need_same) + len(keep), len(rows))


class TestMeasuredFactsArePinned(unittest.TestCase):
    def test_prompts_state_the_boundary_that_was_failing(self):
        for needle in ("response", "presuppose", "Endorsement"):
            self.assertIn(needle, META_SYSTEM)
        for needle in ("missing", "acronym", "referent", "bus crashes"):
            self.assertIn(needle, SAME_SYSTEM)

    def test_meta_and_same_prompts_are_distinct_objects(self):
        """label_hybrid dispatches on prompt identity, so these must not be equal."""
        self.assertIsNot(META_SYSTEM, SAME_SYSTEM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
