"""Unit tests for benchmark exemplar agreement metrics."""

# flake8: noqa: E402

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from benchmark.exemplar_agreement import (
    build_assignment_map,
    build_code_map,
    jaccard_overlap,
    krippendorff_alpha,
    macro_jaccard,
    ontology_weighted_disagreement,
)


class TestBuildCodeMap(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(build_code_map([]), {})

    def test_single_row(self):
        rows = [{"id": "1", "code": "A"}]
        self.assertEqual(build_code_map(rows), {"A": {"1"}})

    def test_multiple_exemplars_per_code(self):
        rows = [
            {"id": "1", "code": "A"},
            {"id": "2", "code": "A"},
            {"id": "3", "code": "B"},
        ]
        result = build_code_map(rows)
        self.assertEqual(result["A"], {"1", "2"})
        self.assertEqual(result["B"], {"3"})


class TestBuildAssignmentMap(unittest.TestCase):
    def test_basic(self):
        rows = [{"id": "1", "code": "A"}, {"id": "2", "code": "B"}]
        self.assertEqual(build_assignment_map(rows), {"1": "A", "2": "B"})


class TestJaccardOverlap(unittest.TestCase):
    def test_identical(self):
        cm = {"A": {"1", "2"}, "B": {"3"}}
        result = jaccard_overlap(cm, cm)
        self.assertEqual(result["A"], 1.0)
        self.assertEqual(result["B"], 1.0)

    def test_no_overlap(self):
        cm_a = {"A": {"1", "2"}}
        cm_b = {"B": {"1", "2"}}
        result = jaccard_overlap(cm_a, cm_b)
        self.assertEqual(result["A"], 0.0)
        self.assertEqual(result["B"], 0.0)

    def test_partial(self):
        cm_a = {"A": {"1", "2", "3"}}
        cm_b = {"A": {"2", "3", "4"}}
        result = jaccard_overlap(cm_a, cm_b)
        self.assertAlmostEqual(result["A"], 0.5)


class TestMacroJaccard(unittest.TestCase):
    def test_identical(self):
        cm = {"A": {"1"}, "B": {"2"}}
        self.assertAlmostEqual(macro_jaccard(cm, cm), 1.0)

    def test_no_overlap(self):
        cm_a = {"A": {"1"}}
        cm_b = {"B": {"1"}}
        self.assertAlmostEqual(macro_jaccard(cm_a, cm_b), 0.0)

    def test_mixed(self):
        cm_a = {"A": {"1", "2"}, "B": {"3"}}
        cm_b = {"A": {"2", "3"}, "B": {"3"}}
        # A: 1/3 approx 0.333, B: 1/1 = 1.0 macro = 0.667
        self.assertAlmostEqual(macro_jaccard(cm_a, cm_b), 0.6666667, places=6)


class TestKrippendorffAlpha(unittest.TestCase):
    def test_perfect_agreement(self):
        mc = {"1": "A", "2": "B", "3": "A"}
        hc = {"1": "A", "2": "B", "3": "A"}
        self.assertAlmostEqual(krippendorff_alpha(mc, hc), 1.0, places=4)

    def test_no_agreement(self):
        mc = {"1": "A", "2": "A"}
        hc = {"1": "B", "2": "B"}
        alpha = krippendorff_alpha(mc, hc)
        self.assertAlmostEqual(alpha, 0.0, places=4)

    def test_single_unit(self):
        mc = {"1": "A"}
        hc = {"1": "A"}
        self.assertAlmostEqual(krippendorff_alpha(mc, hc), 0.0, places=4)

    def test_partial(self):
        mc = {"1": "A", "2": "A", "3": "B", "4": "B"}
        hc = {"1": "A", "2": "B", "3": "B", "4": "A"}
        alpha = krippendorff_alpha(mc, hc)
        self.assertTrue(alpha < 0.5)


class TestOntologyWeighted(unittest.TestCase):
    def test_identical_assignments(self):
        mc = {"1": {"id": "1", "code": "A", "tag": "X"}}
        hc = {"1": {"id": "1", "code": "A", "tag": "X"}}
        dist = {"X": {"X": 0.0}}
        result = ontology_weighted_disagreement(mc, hc, dist)
        self.assertAlmostEqual(result.get("X", 0.0), 0.0, places=4)

    def test_different_assignments_penalised(self):
        mc = {"1": {"id": "1", "code": "A", "tag": "X"}}
        hc = {"1": {"id": "1", "code": "B", "tag": "Y"}}
        dist = {"X": {"Y": 0.5}, "Y": {"X": 0.5}}
        result = ontology_weighted_disagreement(mc, hc, dist)
        self.assertGreater(result.get("X", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
