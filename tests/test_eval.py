"""Tests for the eval harness itself. No network, no GPU, no cost.

The harness is about to be the thing that decides whether a checkpoint ships, so
its arithmetic needs to be checked against cases where the right answer is known
by hand. A silently wrong AUC would approve a worse model.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import gates as G
from eval import metrics as M
from eval.dataset import (GATING_CONFIDENCES, LABELS, POSITIVE_LABELS, Pair,
                          by_reference, load)
from eval.scorers import GPU_OPT_IN, ReplayScorer, build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pair(pid, label, baseline=None, conf="certain", ref="R"):
    return Pair(id=pid, reference=ref, candidate=f"c-{pid}", label=label,
                confidence=conf, baseline=baseline, group=pid.rsplit("-", 1)[0])


class TestDataset(unittest.TestCase):
    def setUp(self):
        self.pairs = load()

    def test_loads_and_validates(self):
        self.assertGreaterEqual(len(self.pairs), 20)

    def test_every_label_is_represented(self):
        seen = {p.label for p in self.pairs}
        self.assertEqual(seen, set(LABELS),
                         "each of the five classes needs at least one real example")

    def test_positive_and_negative_both_present(self):
        pos = [p for p in self.pairs if p.gold_positive]
        neg = [p for p in self.pairs if not p.gold_positive]
        self.assertTrue(pos and neg, "a one-sided set cannot measure precision")

    def test_gating_pairs_dominate(self):
        gating = [p for p in self.pairs if p.gates]
        self.assertGreater(len(gating) / len(self.pairs), 0.8,
                           "too many debatable labels to gate a release on")

    def test_grouping_is_lossless(self):
        groups = by_reference(self.pairs)
        self.assertEqual(sum(len(v) for v in groups.values()), len(self.pairs))
        self.assertLess(len(groups), len(self.pairs), "grouping should save requests")

    def test_rejects_unknown_label(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"id": "a", "reference": "r", "candidate": "c",
                                 "label": "sort_of_similar"}) + "\n")
            path = fh.name
        with self.assertRaises(ValueError):
            load(path)
        os.unlink(path)

    def test_rejects_duplicate_id(self):
        row = {"id": "a", "reference": "r", "candidate": "c", "label": "unrelated"}
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            path = fh.name
        with self.assertRaises(ValueError):
            load(path)
        os.unlink(path)

    def test_rejects_out_of_range_baseline(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"id": "a", "reference": "r", "candidate": "c",
                                 "label": "unrelated", "baseline": 4.2}) + "\n")
            path = fh.name
        with self.assertRaises(ValueError):
            load(path)
        os.unlink(path)

    def test_label_order_is_pinned(self):
        """A checkpoint's id2label must match this order. Reordering silently
        inverts every metric while the numbers still look plausible."""
        self.assertEqual(LABELS, ["unrelated", "incidental", "meta",
                                  "same_paraphrase", "same_verbatim"])
        self.assertEqual(POSITIVE_LABELS, {"same_verbatim", "same_paraphrase"})


class TestRanking(unittest.TestCase):
    def test_auc_perfect(self):
        self.assertEqual(M.roc_auc([0.9, 0.8], [0.2, 0.1]), 1.0)

    def test_auc_inverted(self):
        self.assertEqual(M.roc_auc([0.1, 0.2], [0.8, 0.9]), 0.0)

    def test_auc_all_ties_is_half(self):
        """Real reranker output has exact ties at 0.0, so this path is live."""
        self.assertEqual(M.roc_auc([0.5, 0.5], [0.5, 0.5]), 0.5)

    def test_auc_single_tie_straddling(self):
        # one positive above, one tied with the single negative -> 0.75
        self.assertAlmostEqual(M.roc_auc([0.9, 0.3], [0.3]), 0.75)

    def test_auc_needs_both_sides(self):
        self.assertIsNone(M.roc_auc([0.9], []))
        self.assertIsNone(M.roc_auc([], [0.1]))

    def test_average_precision_perfect(self):
        self.assertEqual(M.average_precision([(0.9, 1), (0.8, 1), (0.2, 0)]), 1.0)

    def test_average_precision_worst(self):
        # both positives ranked last: 1/3 and 2/4 -> mean 0.41666
        ap = M.average_precision([(0.9, 0), (0.8, 0), (0.7, 1), (0.6, 1)])
        self.assertAlmostEqual(ap, (1 / 3 + 2 / 4) / 2)

    def test_separation_positive_when_separable(self):
        margin, wp, bn = M.separation([0.7, 0.9], [0.1, 0.3])
        self.assertAlmostEqual(margin, 0.4)
        self.assertEqual((wp, bn), (0.7, 0.3))

    def test_separation_negative_when_interleaved(self):
        margin, _, _ = M.separation([0.2, 0.9], [0.1, 0.8])
        self.assertLess(margin, 0)


class TestThresholded(unittest.TestCase):
    def test_confusion_counts(self):
        c = M.confusion_at([(0.9, 1), (0.6, 0), (0.4, 1), (0.1, 0)], 0.5)
        self.assertEqual((c["tp"], c["fp"], c["fn"], c["tn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(c["precision"], 0.5)
        self.assertAlmostEqual(c["recall"], 0.5)
        self.assertAlmostEqual(c["f1"], 0.5)

    def test_best_threshold_finds_the_separable_split(self):
        best = M.best_threshold([(0.9, 1), (0.8, 1), (0.3, 0), (0.1, 0)])
        self.assertEqual(best["f1"], 1.0)
        self.assertLessEqual(best["threshold"], 0.8)
        self.assertGreater(best["threshold"], 0.3)

    def test_coverage_at_zero_threshold_is_everything(self):
        curve = M.coverage_curve([(0.9, 1), (0.1, 0)])
        self.assertAlmostEqual(curve[0]["coverage"], 1.0)
        self.assertAlmostEqual(curve[-1]["coverage"], 0.0)

    def test_perfect_precision_coverage(self):
        # 2 positives at 0.9/0.8, 2 negatives at 0.3/0.1 -> can accept half the set
        cov, thr = M.max_coverage_at_perfect_precision(
            [(0.9, 1), (0.8, 1), (0.3, 0), (0.1, 0)])
        self.assertAlmostEqual(cov, 0.5)
        self.assertIsNotNone(thr)

    def test_perfect_precision_impossible_when_top_is_negative(self):
        cov, _ = M.max_coverage_at_perfect_precision([(0.99, 0), (0.5, 1)])
        self.assertEqual(cov, 0.0)


class TestCalibration(unittest.TestCase):
    def test_brier_perfect_is_zero(self):
        self.assertEqual(M.brier([(1.0, 1), (0.0, 0)]), 0.0)

    def test_brier_confidently_wrong_is_one(self):
        self.assertEqual(M.brier([(1.0, 0), (0.0, 1)]), 1.0)

    def test_ece_zero_when_calibrated(self):
        """Ten 0.95s of which one is wrong sits close to its own confidence."""
        ece, _ = M.calibration([(0.95, 1)] * 19 + [(0.95, 0)], bins=10)
        self.assertLess(ece, 0.05)

    def test_ece_large_when_overconfident(self):
        ece, _ = M.calibration([(0.99, 0)] * 10, bins=10)
        self.assertGreater(ece, 0.9)

    def test_reliability_bins_cover_the_unit_interval(self):
        _, rows = M.calibration([(0.05, 0), (0.99, 1), (1.0, 1)], bins=10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(r["n"] for r in rows), 3,
                         "a score of exactly 1.0 must land in the top bin")


class TestPerClass(unittest.TestCase):
    def test_wrong_side_direction_depends_on_the_class(self):
        preds = [(_pair("a-1", "same_paraphrase"), 0.2, None),
                 (_pair("b-1", "unrelated"), 0.2, None)]
        pc = M.per_class(preds)
        self.assertEqual(pc["same_paraphrase"]["n_wrong_side"], 1,
                         "a positive below threshold is wrong")
        self.assertEqual(pc["unrelated"]["n_wrong_side"], 0,
                         "a negative below threshold is right")

    def test_wrong_side_honors_a_custom_threshold(self):
        """`per_class` used to silently ignore its own threshold argument: it
        hardcoded the module default of 0.5 no matter what `evaluate(preds, 0.70)`
        was called with, so a report run at a custom threshold showed the right
        aggregate numbers next to a wrong per-class count. 0.6 is a positive that is
        fine at 0.5 but wrong at 0.7; only a threshold-aware call should catch it."""
        preds = [(_pair("a-1", "same_paraphrase"), 0.6, None)]
        self.assertEqual(M.per_class(preds, threshold=0.5)["same_paraphrase"]["n_wrong_side"], 0)
        self.assertEqual(M.per_class(preds, threshold=0.7)["same_paraphrase"]["n_wrong_side"], 1)

    def test_evaluate_threads_its_threshold_into_per_class(self):
        """`evaluate()` must pass ITS OWN threshold argument to `per_class`, not the
        default. This is the exact bug: at_threshold was correct at 0.70 while
        per_class stayed pinned to 0.5 in the same report."""
        preds = [(_pair("a-1", "same_paraphrase"), 0.6, None)]
        report = M.evaluate(preds, threshold=0.7)
        self.assertEqual(report["at_threshold"]["fn"], 1,
                         "at_threshold correctly saw this as a miss at 0.70")
        self.assertEqual(report["per_class"]["same_paraphrase"]["n_wrong_side"], 1,
                         "per_class must agree with at_threshold in the same report")

    def test_class_confusion_is_none_without_distributions(self):
        preds = [(_pair("a-1", "unrelated"), 0.1, None)]
        self.assertIsNone(M.class_confusion(preds))

    def test_class_confusion_uses_argmax(self):
        dist = {l: 0.05 for l in LABELS}
        dist["meta"] = 0.8
        preds = [(_pair("a-1", "same_paraphrase"), 0.1, dist)]
        cm = M.class_confusion(preds)
        self.assertEqual(cm["same_paraphrase"]["meta"], 1)


class TestGates(unittest.TestCase):
    def _run(self, scores):
        preds = []
        for pid, label, s in scores:
            preds.append((_pair(pid, label), s, None))
        report = M.evaluate(preds)
        return G.check(preds, report), report

    def test_unlock_and_regression_sets_are_disjoint(self):
        self.assertFalse(set(G.UNLOCK_PAIRS) & set(G.REGRESSION_PAIRS))

    def test_every_gated_id_exists_in_the_dataset(self):
        ids = {p.id for p in load()}
        missing = (set(G.UNLOCK_PAIRS) | set(G.REGRESSION_PAIRS)) - ids
        self.assertFalse(missing, f"gates reference unknown pairs: {missing}")

    def test_gated_ids_are_not_debatable(self):
        """A release must not hinge on a label we are unsure of."""
        conf = {p.id: p.confidence for p in load()}
        for pid in set(G.UNLOCK_PAIRS) | set(G.REGRESSION_PAIRS):
            self.assertIn(conf[pid], GATING_CONFIDENCES, f"{pid} is debatable")

    def test_gate_directions_match_the_labels(self):
        lab = {p.id: p.label for p in load()}
        for pid in G.UNLOCK_PAIRS:
            self.assertIn(lab[pid], POSITIVE_LABELS,
                          f"{pid} must clear the threshold but is not a positive")
        for pid in G.REGRESSION_PAIRS:
            self.assertNotIn(lab[pid], POSITIVE_LABELS,
                             f"{pid} must stay below but is a positive")

    def test_missing_pairs_are_skipped_not_failed(self):
        gate, _ = self._run([("ssi-03", "same_paraphrase", 0.9)])
        self.assertTrue(gate["skipped"])
        rows = {r["id"]: r for r in gate["rows"]}
        # any gated pair that was not scored must report None, not False
        absent = next(pid for pid in G.UNLOCK_PAIRS if pid != "ssi-03")
        self.assertIsNone(rows[absent]["passed"])

    def test_cross_lingual_pair_is_out_of_scope_not_gated(self):
        """The project is scoped to English. ptf-03 is the Arabic pair: it was the worst
        measured failure at 0.012, reached 0.8685 with cross-lingual training, then fell
        to 0.4519 when English-only. Gating on it while training English-only is what
        produced an unresolvable threshold, so it is kept as data and not gated."""
        self.assertIn("ptf-03", G.OUT_OF_SCOPE)
        self.assertNotIn("ptf-03", G.UNLOCK_PAIRS)
        self.assertNotIn("ptf-03", G.REGRESSION_PAIRS)
        self.assertIn("ptf-03", {p.id for p in load()},
                      "the row must survive; only the gating stops")

    def test_not_shippable_when_an_unlock_fails(self):
        scores = [(pid, "same_paraphrase", 0.1) for pid in G.UNLOCK_PAIRS]
        scores += [(pid, "unrelated", 0.01) for pid in G.REGRESSION_PAIRS]
        gate, _ = self._run(scores)
        self.assertFalse(gate["shippable"])

    def test_not_shippable_when_a_regression_breaks(self):
        scores = [(pid, "same_paraphrase", 0.99) for pid in G.UNLOCK_PAIRS]
        scores += [(pid, "unrelated", 0.99) for pid in G.REGRESSION_PAIRS]
        gate, _ = self._run(scores)
        self.assertFalse(gate["shippable"],
                         "scoring everything high is not an improvement")

    def test_shippable_when_both_sides_hold(self):
        scores = [(pid, "same_paraphrase", 0.9) for pid in G.UNLOCK_PAIRS]
        scores += [(pid, "unrelated", 0.05) for pid in G.REGRESSION_PAIRS]
        gate, _ = self._run(scores)
        self.assertTrue(gate["shippable"])


class TestScorers(unittest.TestCase):
    def test_replay_reproduces_the_recorded_baseline(self):
        pairs = load()
        sc = ReplayScorer(pairs)
        for ref, group in by_reference(pairs).items():
            for pair, (score, probs) in zip(group, sc.score(ref, group)):
                self.assertEqual(score, pair.baseline)
                self.assertIsNone(probs)

    def test_replay_returns_none_rather_than_zero(self):
        """Defaulting an unmeasured pair to 0.0 would flatter any new model on the
        negatives and punish it on the positives."""
        sc = ReplayScorer([_pair("x-1", "unrelated", baseline=None)])
        self.assertIsNone(sc.score("R", [_pair("x-1", "unrelated")])[0][0])

    def test_local_scorer_refuses_without_the_gpu_opt_in(self):
        prior = os.environ.pop(GPU_OPT_IN, None)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                build("local", [], path="/nonexistent")
            self.assertIn(GPU_OPT_IN, str(ctx.exception))
        finally:
            if prior is not None:
                os.environ[GPU_OPT_IN] = prior

    def test_unknown_scorer_rejected(self):
        with self.assertRaises(ValueError):
            build("vibes", [])


class TestRunner(unittest.TestCase):
    """End to end through the CLI, still free: the replay scorer needs no network."""

    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "eval.run", "--no-colour", *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)

    def test_replay_run_succeeds(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT SHIPPABLE", r.stdout,
                      "the served model does not pass its own gates yet")

    def test_save_then_compare(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.json")
            self.assertEqual(self._run("--save", a).returncode, 0)
            with open(a) as fh:
                blob = json.load(fh)
            for key in ("scorer", "threshold", "cases", "report", "gates"):
                self.assertIn(key, blob)
            self.assertFalse(blob["gates"]["shippable"])
            r = self._run("--compare", a, a)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("separation_margin", r.stdout)

    def test_describe(self):
        r = self._run("--describe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("same_paraphrase", r.stdout)

    def test_custom_threshold_label_matches_what_was_computed(self):
        """Regression test for the render() bug: passing --threshold 0.7 used to
        compute at_threshold and the gate correctly at 0.7 while printing "precision
        @ 0.5" and "wrong side of 0.5" right next to those numbers, and marking
        per-case pass/fail at 0.5 regardless. The label text is itself the check
        here, not just the underlying numbers."""
        r = self._run("--threshold", "0.7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wrong side of 0.7", r.stdout)
        self.assertIn("precision @ 0.7", r.stdout)
        self.assertIn("recall @ 0.7", r.stdout)
        self.assertNotIn("wrong side of 0.5", r.stdout)
        self.assertNotIn("precision @ 0.5", r.stdout)


class TestBaselineFindings(unittest.TestCase):
    """Assertions about the CURRENT served model, so a regression is loud.

    These are deliberately phrased as 'still broken'. When the fine-tune lands they
    will fail, and that failure is the success signal. Same trick as
    test_paraphrase_gap_is_still_open in the integration suite.
    """

    def setUp(self):
        pairs = load()
        preds, _ = [], None
        for ref, group in by_reference(pairs).items():
            for pair, (s, pr) in zip(group, ReplayScorer(pairs).score(ref, group)):
                if s is not None:
                    preds.append((pair, s, pr))
        self.preds = preds
        self.report = M.evaluate(preds)

    def test_no_threshold_separates_the_set_today(self):
        self.assertLess(self.report["separation_margin"], 0)

    def test_meta_commentary_outscores_every_real_paraphrase(self):
        """The false-accept half of the problem, which the recall framing hides.

        A post about people reacting to the claim scores 0.813 while a faithful
        restatement scores 0.288. Fixing recall alone would not fix this.
        """
        best_neg = self.report["best_negative"]
        para = self.report["per_class"]["same_paraphrase"]["max"]
        self.assertGreater(best_neg, para)

    def test_paraphrase_class_averages_below_threshold(self):
        self.assertLess(self.report["per_class"]["same_paraphrase"]["mean"], 0.5)

    def test_verbatim_is_already_solved(self):
        """Whatever we train must not regress the easy case."""
        self.assertGreater(self.report["per_class"]["same_verbatim"]["max"], 0.99)


if __name__ == "__main__":
    unittest.main(verbosity=2)
