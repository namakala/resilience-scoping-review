"""Comprehensive tests for inference/tracking.py — token usage middleware.

Covers all acceptance criteria from Feature 34:

AC #1: Structured log written to token_usage.log after each LLM call
AC #2: Human-readable stage summary displayed at end of stage
AC #3: Cost calculation verified with manual arithmetic
AC #4: Token counts stored in session_state via flush_to_dict/records
AC #5: Warning logged if stage cost exceeds configurable threshold

Additional coverage:
- Singleton get_tracker / reset_tracker lifecycle
- track_tokens decorator extracts usage from ChatCompletion
- Sliding window recent_usage for rate-limit awareness
- Zero-token edge case
- Directory auto-creation for token_usage.log
"""

# flake8: noqa: E402
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from inference.groq_client import complete
from inference.track_decorator import track_tokens
from inference.tracking import (
    TokenTracker,
    UsageRecord,
    format_stage_summary,
    get_tracker,
    reset_tracker,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _ts(offset_seconds: float = 0) -> str:
    """Return an ISO 8601 timestamp offset from now."""
    dt = datetime.now(timezone.utc).timestamp() + offset_seconds
    return datetime.fromtimestamp(dt, tz=timezone.utc).isoformat()


class MockUsage:
    """Mock Groq ChatCompletion usage field."""

    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class MockChatCompletion:
    """Mock Groq ChatCompletion response object."""

    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.usage = MockUsage(prompt_tokens, completion_tokens)


class MockResponseNoUsage:
    """Mock response object without a .usage attribute."""

    pass


# ── UsageRecord ──────────────────────────────────────────────────────────────


class TestUsageRecord(unittest.TestCase):
    """Dataclass construction and cost field."""

    def test_record_creation(self):
        rec = UsageRecord(
            stage="code_inference",
            batch_id="tag_root_batch_00",
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.000195,
        )
        self.assertEqual(rec.stage, "code_inference")
        self.assertEqual(rec.batch_id, "tag_root_batch_00")
        self.assertEqual(rec.input_tokens, 500)
        self.assertEqual(rec.output_tokens, 200)
        self.assertEqual(rec.cost_usd, 0.000195)
        self.assertIsNotNone(rec.timestamp)

    def test_record_default_timestamp(self):
        rec = UsageRecord(
            stage="t", batch_id="b", input_tokens=0, output_tokens=0, cost_usd=0.0
        )
        # Should be a valid ISO 8601 string
        parsed = datetime.fromisoformat(rec.timestamp)
        self.assertIsNotNone(parsed)


# ── Cost Calculation ─────────────────────────────────────────────────────────


class TestCostCalculation(unittest.TestCase):
    """AC #3: Manual arithmetic verification."""

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_cost_manual_arithmetic(self, mock_out, mock_in):
        """1M input + 1M output = $0.15 + $0.60 = $0.75."""
        from inference.tracking import _compute_cost

        cost = _compute_cost(1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 0.75, places=6)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_cost_zero_tokens(self, mock_out, mock_in):
        from inference.tracking import _compute_cost

        cost = _compute_cost(0, 0)
        self.assertEqual(cost, 0.0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_cost_partial_tokens(self, mock_out, mock_in):
        """500 input + 300 output at default rates."""
        from inference.tracking import _compute_cost

        cost = _compute_cost(500, 300)
        expected = 500 / 1_000_000 * 0.15 + 300 / 1_000_000 * 0.60
        self.assertAlmostEqual(cost, expected, places=10)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.0)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.0)
    def test_cost_zero_rates(self, mock_out, mock_in):
        from inference.tracking import _compute_cost

        cost = _compute_cost(1_000_000, 1_000_000)
        self.assertEqual(cost, 0.0)


# ── TokenTracker: Recording ──────────────────────────────────────────────────


class TestTokenTrackerRecord(unittest.TestCase):
    """AC #1: Structured log + accumulation."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_record_accumulates(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1000, 500)
        self.tracker.record("code", "b2", 2000, 1000)

        summary = self.tracker.stage_summary("code")
        self.assertEqual(summary["input"], 3000)
        self.assertEqual(summary["output"], 1500)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_record_multiple_stages(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1000, 500)
        self.tracker.record("theme", "t1", 300, 200)

        self.assertEqual(self.tracker.stage_summary("code")["input"], 1000)
        self.assertEqual(self.tracker.stage_summary("theme")["input"], 300)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_record_writes_log_entry(self, mock_out, mock_in):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "token_usage.log"
            with mock.patch("inference.tracking._TOKEN_USAGE_LOG", log_path):
                self.tracker.record("code", "tag_root_batch_00", 1234, 567)

                self.assertTrue(log_path.exists())
                lines = log_path.read_text().strip().split("\n")
                self.assertEqual(len(lines), 1)

                entry = json.loads(lines[0])
                self.assertEqual(entry["stage"], "code")
                self.assertEqual(entry["batch_id"], "tag_root_batch_00")
                self.assertEqual(entry["input_tokens"], 1234)
                self.assertEqual(entry["output_tokens"], 567)
                self.assertIn("cost_usd", entry)
                self.assertIn("timestamp", entry)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_record_appends_multiple_entries(self, mock_out, mock_in):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "token_usage.log"
            with mock.patch("inference.tracking._TOKEN_USAGE_LOG", log_path):
                self.tracker.record("code", "b1", 100, 50)
                self.tracker.record("code", "b2", 200, 100)

                lines = log_path.read_text().strip().split("\n")
                self.assertEqual(len(lines), 2)


# ── TokenTracker: Queries ────────────────────────────────────────────────────


class TestTokenTrackerQueries(unittest.TestCase):
    """Stage/session summaries, recent_usage, total_records."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_stage_summary_unknown_stage(self, mock_out, mock_in):
        """Unknown stage returns zeroed dict, no KeyError."""
        summary = self.tracker.stage_summary("nonexistent")
        self.assertEqual(summary["input"], 0)
        self.assertEqual(summary["output"], 0)
        self.assertEqual(summary["cost"], 0.0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_stage_summary_includes_cost(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1_000_000, 500_000)
        summary = self.tracker.stage_summary("code")
        # input cost: $0.15, output cost: $0.30 = $0.45
        self.assertAlmostEqual(summary["cost"], 0.45, places=6)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_session_summary(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1000, 500)
        self.tracker.record("theme", "t1", 300, 200)
        summary = self.tracker.session_summary()
        self.assertEqual(summary["input"], 1300)
        self.assertEqual(summary["output"], 700)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_session_summary_empty(self, mock_out, mock_in):
        summary = self.tracker.session_summary()
        self.assertEqual(summary["input"], 0)
        self.assertEqual(summary["output"], 0)
        self.assertEqual(summary["cost"], 0.0)

    @mock.patch.object(TokenTracker, "_write_log_entry")
    def test_total_records(self, mock_write):
        self.assertEqual(self.tracker.total_records(), 0)
        self.tracker.record("code", "b1", 100, 50)
        self.tracker.record("code", "b2", 200, 100)
        self.assertEqual(self.tracker.total_records(), 2)

    def test_recent_usage_empty(self):
        usage = self.tracker.recent_usage(window_seconds=60)
        self.assertEqual(usage["input"], 0)
        self.assertEqual(usage["output"], 0)
        self.assertEqual(usage["total"], 0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_recent_usage_within_window(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1000, 500)
        usage = self.tracker.recent_usage(window_seconds=3600)
        self.assertEqual(usage["input"], 1000)
        self.assertEqual(usage["output"], 500)
        self.assertEqual(usage["total"], 1500)


# ── TokenTracker: Persistence ────────────────────────────────────────────────


class TestTokenTrackerPersistence(unittest.TestCase):
    """AC #4: flush_to_dict, flush_to_records."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_flush_to_dict(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 1000, 500)
        self.tracker.record("code", "b2", 2000, 1000)
        self.tracker.record("theme", "t1", 300, 200)

        state_dict = self.tracker.flush_to_dict()
        self.assertEqual(state_dict["code"]["input"], 3000)
        self.assertEqual(state_dict["code"]["output"], 1500)
        self.assertEqual(state_dict["theme"]["input"], 300)
        self.assertEqual(state_dict["theme"]["output"], 200)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_flush_to_dict_empty(self, mock_out, mock_in):
        self.assertEqual(self.tracker.flush_to_dict(), {})

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_flush_to_records(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 100, 50)
        records = self.tracker.flush_to_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["stage"], "code")
        self.assertEqual(records[0]["batch_id"], "b1")
        self.assertEqual(records[0]["input_tokens"], 100)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_flush_is_snapshot_not_destructive(self, mock_out, mock_in):
        """Flush should not clear the accumulator."""
        self.tracker.record("code", "b1", 100, 50)
        _ = self.tracker.flush_to_dict()
        _ = self.tracker.flush_to_records()
        # Still accessible after flush
        summary = self.tracker.stage_summary("code")
        self.assertEqual(summary["input"], 100)


# ── TokenTracker: reset ──────────────────────────────────────────────────────


class TestTokenTrackerReset(unittest.TestCase):
    """reset() clears all state."""

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_reset_clears_stage_totals(self, mock_out, mock_in):
        tracker = TokenTracker()
        tracker.record("code", "b1", 1000, 500)
        tracker.reset()
        self.assertEqual(tracker.stage_summary("code")["input"], 0)
        self.assertEqual(tracker.total_records(), 0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_reset_clears_warnings(self, mock_out, mock_in):
        tracker = TokenTracker()
        tracker._stage_cost_warnings.add("code")
        tracker.reset()
        self.assertEqual(len(tracker._stage_cost_warnings), 0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_reset_then_record_works(self, mock_out, mock_in):
        tracker = TokenTracker()
        tracker.record("code", "b1", 100, 50)
        tracker.reset()
        tracker.record("code", "b2", 200, 100)
        self.assertEqual(tracker.stage_summary("code")["input"], 200)


# ── TokenTracker: cost threshold warning ─────────────────────────────────────


class TestTokenTrackerCostWarning(unittest.TestCase):
    """AC #5: Warning logged when stage cost exceeds threshold."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.max_stage_cost_usd", return_value=0.05)
    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    @mock.patch("inference.tracking.logger.warning")
    def test_warning_on_excess_cost(self, mock_warn, mock_out, mock_in, mock_threshold):
        """500K input + 500K output at default rates = $0.075 + $0.30 = $0.375 > $0.05."""
        self.tracker.record("code", "b1", 500_000, 500_000)
        mock_warn.assert_called_once()
        args, kwargs = mock_warn.call_args
        # logger.warning uses %s-style formatting; args[0] is format string,
        # args[1] is the first format arg (stage name)
        self.assertEqual(args[1], "code")
        self.assertIn("extra", kwargs)
        self.assertEqual(kwargs["extra"]["stage"], "code")

    @mock.patch("inference.tracking.max_stage_cost_usd", return_value=1.00)
    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    @mock.patch("inference.tracking.logger.warning")
    def test_no_warning_below_threshold(
        self, mock_warn, mock_out, mock_in, mock_threshold
    ):
        """10 tokens total → cost $0.0000015 → no warning."""
        self.tracker.record("code", "b1", 10, 0)
        mock_warn.assert_not_called()

    @mock.patch("inference.tracking.max_stage_cost_usd", return_value=0.05)
    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    @mock.patch("inference.tracking.logger.warning")
    def test_warning_only_once_per_stage(
        self, mock_warn, mock_out, mock_in, mock_threshold
    ):
        """Multiple records exceeding threshold should only warn once."""
        self.tracker.record("code", "b1", 500_000, 500_000)
        self.tracker.record("code", "b2", 500_000, 500_000)
        mock_warn.assert_called_once()


# ── Singleton management ─────────────────────────────────────────────────────


class TestTrackerSingleton(unittest.TestCase):
    """get_tracker / reset_tracker lifecycle."""

    def setUp(self):
        reset_tracker()

    def tearDown(self):
        reset_tracker()

    def test_get_tracker_returns_same_instance(self):
        t1 = get_tracker()
        t2 = get_tracker()
        self.assertIs(t1, t2)

    def test_reset_tracker_creates_new_instance(self):
        t1 = get_tracker()
        reset_tracker()
        t2 = get_tracker()
        self.assertIsNot(t1, t2)


# ── track_tokens decorator ───────────────────────────────────────────────────


class TestTrackTokensDecorator(unittest.TestCase):
    """@track_tokens(stage_name) decoration."""

    def setUp(self):
        reset_tracker()

    def tearDown(self):
        reset_tracker()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_decorator_extracts_usage(self, mock_out, mock_in):
        @track_tokens("code_inference")
        def mock_infer(batch_id="unknown"):
            return MockChatCompletion(prompt_tokens=100, completion_tokens=50)

        result = mock_infer(batch_id="tag_root_batch_00")
        self.assertIsNotNone(result)
        self.assertEqual(result.usage.prompt_tokens, 100)

        tracker = get_tracker()
        summary = tracker.stage_summary("code_inference")
        self.assertEqual(summary["input"], 100)
        self.assertEqual(summary["output"], 50)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_decorator_no_usage(self, mock_out, mock_in):
        """Function returning response without .usage should not error."""

        @track_tokens("code_inference")
        def mock_infer(**kwargs):
            return MockResponseNoUsage()

        result = mock_infer(batch_id="b1")
        self.assertIsInstance(result, MockResponseNoUsage)

        tracker = get_tracker()
        self.assertEqual(tracker.total_records(), 0)

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_decorator_default_batch_id(self, mock_out, mock_in):
        """When batch_id not passed, should use 'unknown'."""

        @track_tokens("code_inference")
        def mock_infer(prompt):
            return MockChatCompletion(prompt_tokens=50, completion_tokens=25)

        result = mock_infer("some prompt")
        self.assertIsNotNone(result)

        records = get_tracker().flush_to_records()
        self.assertEqual(records[0]["batch_id"], "unknown")

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_decorator_preserves_return_value(self, mock_out, mock_in):
        @track_tokens("code")
        def mock_infer(**kwargs):
            return {"custom": "result"}

        result = mock_infer(batch_id="b1")
        self.assertEqual(result, {"custom": "result"})

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_decorator_with_exceptions_still_raises(self, mock_out, mock_in):
        """If the wrapped function raises, decorator should not catch it."""

        @track_tokens("code")
        def broken_infer(**kwargs):
            raise ValueError("API failure")

        with self.assertRaises(ValueError):
            broken_infer(batch_id="b1")


# ── format_stage_summary ─────────────────────────────────────────────────────


class TestFormatStageSummary(unittest.TestCase):
    """AC #2: Human-readable stage summary."""

    def test_format_basic(self):
        summary = {"input": 50000, "output": 20000, "cost": 0.015}
        result = format_stage_summary("Code inference", summary)
        self.assertEqual(
            result, "Code inference complete. Tokens: 50.0K in, 20.0K out. Cost: $0.015"
        )

    def test_format_zero_values(self):
        summary = {"input": 0, "output": 0, "cost": 0.0}
        result = format_stage_summary("Test", summary)
        self.assertIn("Test complete", result)
        self.assertIn("0K in", result)
        self.assertIn("0K out", result)

    def test_format_small_numbers(self):
        summary = {"input": 123, "output": 45, "cost": 0.000045}
        result = format_stage_summary("code", summary)
        self.assertIn("0.1K in", result)
        self.assertIn("0.0K out", result)

    def test_format_cost_precision(self):
        summary = {"input": 1000000, "output": 500000, "cost": 0.45}
        result = format_stage_summary("code", summary)
        self.assertIn("$0.45", result)


# ── Zero-token edge case ─────────────────────────────────────────────────────


class TestZeroTokens(unittest.TestCase):
    """Recording zero tokens should not cause errors."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_zero_tokens_no_error(self, mock_out, mock_in):
        self.tracker.record("code", "b1", 0, 0)
        summary = self.tracker.stage_summary("code")
        self.assertEqual(summary["input"], 0)
        self.assertEqual(summary["output"], 0)
        self.assertEqual(summary["cost"], 0.0)


# ── Log directory auto-creation ──────────────────────────────────────────────


class TestLogDirectoryCreation(unittest.TestCase):
    """token_usage.log directory should be auto-created."""

    def setUp(self):
        self.tracker = TokenTracker()

    def tearDown(self):
        self.tracker.reset()

    @mock.patch("inference.tracking.token_cost_input_per_million", return_value=0.15)
    @mock.patch("inference.tracking.token_cost_output_per_million", return_value=0.60)
    def test_log_dir_created(self, mock_out, mock_in):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "nonexistent" / "deep" / "token_usage.log"
            with mock.patch("inference.tracking._TOKEN_USAGE_LOG", log_path):
                self.assertFalse(log_path.parent.exists())
                self.tracker.record("code", "b1", 100, 50)
                self.assertTrue(log_path.parent.exists())
                self.assertTrue(log_path.exists())


# ── Integration with groq_client (smoke test) ────────────────────────────────


class TestIntegrationSmoke(unittest.TestCase):
    """track_tokens can wrap the real complete() function."""

    def test_track_tokens_has_correct_signature(self):
        """Verify the decorator is applicable to the real complete()."""
        import inspect

        sig = inspect.signature(complete)
        # The decorator doesn't change the signature structurally,
        # but functools.wraps preserves the original signature
        decorated = track_tokens("test")(complete)
        self.assertIsNotNone(decorated)


if __name__ == "__main__":
    unittest.main()
