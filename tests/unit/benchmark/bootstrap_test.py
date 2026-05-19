"""Unit tests for bootstrap CI utility."""

# flake8: noqa: E402

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from benchmark.bootstrap import bootstrap_ci, bootstrap_ci_dict


class TestBootstrapCI(unittest.TestCase):
    def test_identical_data(self):
        rows = [{"id": str(i), "code": "A"} for i in range(10)]

        def metric_fn(ra, rb, **kw):
            return 1.0

        result = bootstrap_ci(metric_fn, rows, rows, n_iterations=50, seed=42)
        self.assertAlmostEqual(result["point_estimate"], 1.0)
        self.assertAlmostEqual(result["ci_lower"], 1.0)
        self.assertAlmostEqual(result["ci_upper"], 1.0)
        self.assertGreater(result["n_iterations"], 0)

    def test_constant_value(self):
        rows_a = [{"id": str(i), "code": "A"} for i in range(5)]
        rows_b = [{"id": str(i), "code": "B"} for i in range(5)]

        def metric_fn(ra, rb, **kw):
            return 0.5

        result = bootstrap_ci(metric_fn, rows_a, rows_b, n_iterations=50, seed=0)
        self.assertAlmostEqual(result["point_estimate"], 0.5)


class TestBootstrapCIDict(unittest.TestCase):
    def test_dict_metric(self):
        rows_a = [{"id": str(i), "code": "A"} for i in range(10)]
        rows_b = [{"id": str(i), "code": "A"} for i in range(10)]

        def metric_fn(ra, rb, **kw):
            return {"key1": 0.5, "key2": 0.3}

        result = bootstrap_ci_dict(metric_fn, rows_a, rows_b, n_iterations=50, seed=42)
        self.assertIn("key1", result)
        self.assertIn("key2", result)
        self.assertAlmostEqual(result["key1"]["point_estimate"], 0.5, places=4)
        self.assertAlmostEqual(result["key2"]["point_estimate"], 0.3, places=4)


if __name__ == "__main__":
    unittest.main()
