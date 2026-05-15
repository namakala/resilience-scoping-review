"""Tests for inference/batch_processor.py — batch loop and token recording."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.batch_processor import record_tokens, run_batches  # noqa: E402
from inference.batching import Batch  # noqa: E402
from inference.tracking import TokenTracker  # noqa: E402


class FakeItem:
    """Minimal batch item for testing failure_fn."""

    def __init__(self, item_id):
        self.id = item_id


class TestRecordTokens(unittest.TestCase):
    """record_tokens extracts usage from response and records it."""

    def test_records_usage(self):
        tracker = TokenTracker()
        resp = MagicMock()
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 50

        record_tokens(resp, tracker, "code", "batch_01")

        summary = tracker.stage_summary("code")
        self.assertEqual(summary["input"], 100)
        self.assertEqual(summary["output"], 50)

    def test_skips_if_no_usage(self):
        tracker = TokenTracker()
        resp = MagicMock(spec=[])  # no usage attribute
        record_tokens(resp, tracker, "code", "batch_01")
        summary = tracker.stage_summary("code")
        self.assertEqual(summary["input"], 0)
        self.assertEqual(summary["output"], 0)


class TestRunBatches(unittest.TestCase):
    """run_batches orchestrates batch loop with error handling."""

    def test_all_batches_succeed(self):
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        items = [FakeItem(1), FakeItem(2)]
        batch = Batch(tag="T1", items=items, batch_index=0, total_batches=1)
        results_log = []

        def process_fn(c, b, t):
            results_log.append(b.batch_id)
            return ["result_a", "result_b"]

        def failure_fn(c, item, err):
            raise AssertionError("should not be called")

        all_results, tracker = run_batches(
            con,
            [batch],
            process_fn,
            "code",
            failure_fn,
        )

        self.assertEqual(all_results, ["result_a", "result_b"])
        self.assertEqual(results_log, ["tag_T1_batch_00"])

    def test_batch_exception_calls_failure_fn(self):
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        items = [FakeItem(10), FakeItem(20)]
        batch = Batch(tag="T1", items=items, batch_index=0, total_batches=1)
        failed_ids = []

        def process_fn(c, b, t):
            raise RuntimeError("LLM crash")

        def failure_fn(c, item, err):
            failed_ids.append(item.id)

        all_results, _ = run_batches(con, [batch], process_fn, "code", failure_fn)

        self.assertEqual(all_results, [])
        self.assertEqual(failed_ids, [10, 20])

    def test_multiple_batches_preserve_order(self):
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        b1 = Batch(tag="T1", items=[FakeItem(1)], batch_index=0, total_batches=2)
        b2 = Batch(tag="T2", items=[FakeItem(2)], batch_index=1, total_batches=2)

        def process_fn(c, b, t):
            return [f"result_{b.batch_id}"]

        all_results, _ = run_batches(
            con, [b1, b2], process_fn, "code", lambda c, i, e: None
        )

        self.assertEqual(
            all_results, ["result_tag_T1_batch_00", "result_tag_T2_batch_01"]
        )


if __name__ == "__main__":
    unittest.main()
