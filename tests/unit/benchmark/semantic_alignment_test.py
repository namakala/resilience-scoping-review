"""Unit tests for benchmark semantic alignment metrics."""

# flake8: noqa: E402

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import numpy as np
from benchmark.semantic_alignment import (
    code_hybrid_similarity,
    hungarian_alignment,
    max_pooled_hybrid_similarity,
)


class TestCodeHybridSimilarity(unittest.TestCase):
    def test_identical_names_and_exemplars(self):
        emb_cache = {"A": np.ones(384, dtype=np.float64) / np.sqrt(384)}
        sim = code_hybrid_similarity(
            "A",
            "A",
            {"1", "2"},
            {"1", "2"},
            emb_cache,
        )
        self.assertAlmostEqual(sim, 1.0, places=4)

    def test_no_overlap(self):
        emb_cache = {
            "A": np.ones(384, dtype=np.float64) / np.sqrt(384),
            "B": np.ones(384, dtype=np.float64) / np.sqrt(384),
        }
        sim = code_hybrid_similarity(
            "A",
            "B",
            {"1", "2"},
            {"3", "4"},
            emb_cache,
        )
        # Name cosine ~ 1.0, exemplar Jaccard = 0.0
        # Combined: 0.4 * 1.0 + 0.6 * 0.0 = 0.4
        self.assertAlmostEqual(sim, 0.4, places=4)


class TestMaxPooledHybridSimilarity(unittest.TestCase):
    def test_single_code_perfect_match(self):
        emb_cache = {"X": np.ones(384, dtype=np.float64) / np.sqrt(384)}
        cm_a = {"X": {"1", "2"}}
        cm_b = {"X": {"1", "2"}}
        result = max_pooled_hybrid_similarity(cm_a, cm_b, emb_cache)
        self.assertAlmostEqual(result["_macro_avg"], 1.0, places=4)

    def test_no_match(self):
        emb_cache = {
            "A": np.ones(384, dtype=np.float64) / np.sqrt(384),
            "B": np.ones(384, dtype=np.float64) / np.sqrt(384),
        }
        cm_a = {"A": {"1"}}
        cm_b = {"B": {"2"}}
        result = max_pooled_hybrid_similarity(cm_a, cm_b, emb_cache)
        self.assertAlmostEqual(result["_macro_avg"], 0.4, places=4)


class TestHungarianAlignment(unittest.TestCase):
    def test_identical_code_sets(self):
        emb_cache = {"X": np.ones(384, dtype=np.float64) / np.sqrt(384)}
        cm = {"X": {"1", "2"}}
        result = hungarian_alignment(cm, cm, emb_cache)
        self.assertAlmostEqual(result["mean_weight"], 1.0, places=4)
        self.assertAlmostEqual(result["fraction_unmatched"], 0.0)

    def test_no_codes(self):
        emb_cache = {}
        result = hungarian_alignment({}, {}, emb_cache)
        self.assertAlmostEqual(result["mean_weight"], 0.0)
        self.assertAlmostEqual(result["fraction_unmatched"], 1.0)

    def test_symmetric(self):
        emb_cache = {
            "A": np.ones(384, dtype=np.float64) / np.sqrt(384),
            "B": np.ones(384, dtype=np.float64) / np.sqrt(384),
        }
        cm_a = {"A": {"1"}, "B": {"2"}}
        cm_b = {"A": {"1"}, "B": {"2"}}
        r1 = hungarian_alignment(cm_a, cm_b, emb_cache)
        r2 = hungarian_alignment(cm_b, cm_a, emb_cache)
        self.assertAlmostEqual(r1["mean_weight"], r2["mean_weight"], places=4)


if __name__ == "__main__":
    unittest.main()
