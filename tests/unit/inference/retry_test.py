"""Tests for retry and rate-limit handling (Feature 35)."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from groq import BadRequestError, RateLimitError
from inference.batching import Batch, split_batch_in_half
from inference.prompts import PromptBundle
from inference.retry import (
    TokenLimitError,
    call_complete_with_retry,
    infer_batch_with_retry,
)
from utils.exceptions import RetryExhaustedError

# ============================================================================
# split_batch_in_half tests
# ============================================================================


class TestSplitBatchInHalf(unittest.TestCase):
    """Tests for split_batch_in_half utility."""

    def test_split_even(self):
        """AC: Batch of 20 split into 10+10."""
        batch = Batch(
            tag="root",
            items=list(range(20)),
            batch_index=0,
            total_batches=1,
        )
        halves = split_batch_in_half(batch)
        self.assertEqual(len(halves), 2)
        self.assertEqual(len(halves[0].items), 10)
        self.assertEqual(len(halves[1].items), 10)
        self.assertEqual(halves[0].items, list(range(10)))
        self.assertEqual(halves[1].items, list(range(10, 20)))

    def test_split_odd(self):
        """AC: Batch of 21 split into 11+10."""
        batch = Batch(
            tag="root",
            items=list(range(21)),
            batch_index=0,
            total_batches=1,
        )
        halves = split_batch_in_half(batch)
        self.assertEqual(len(halves), 2)
        self.assertEqual(len(halves[0].items), 11)
        self.assertEqual(len(halves[1].items), 10)

    def test_split_single_item(self):
        """AC: Batch of 1 splits into (1, 0)."""
        batch = Batch(
            tag="root",
            items=[42],
            batch_index=0,
            total_batches=1,
        )
        halves = split_batch_in_half(batch)
        self.assertEqual(len(halves[0].items), 1)
        self.assertEqual(len(halves[1].items), 0)
        self.assertEqual(halves[0].items, [42])

    def test_split_empty(self):
        """AC: Empty batch produces two empty batches."""
        batch = Batch(
            tag="root",
            items=[],
            batch_index=0,
            total_batches=1,
        )
        halves = split_batch_in_half(batch)
        self.assertEqual(len(halves[0].items), 0)
        self.assertEqual(len(halves[1].items), 0)

    def test_split_preserves_metadata(self):
        """AC: tag, _prefix, batch_index, total_batches preserved."""
        batch = Batch(
            tag="root",
            items=[1, 2, 3, 4, 5],
            batch_index=0,
            total_batches=1,
        )
        batch._prefix = "test"
        halves = split_batch_in_half(batch)
        for h in halves:
            self.assertEqual(h.tag, "root")
            self.assertEqual(h._prefix, "test")
        self.assertEqual(halves[0].batch_index, 0)
        self.assertEqual(halves[0].total_batches, 2)
        self.assertEqual(halves[1].batch_index, 1)
        self.assertEqual(halves[1].total_batches, 2)

    def test_split_does_not_mutate_original(self):
        """AC: Original batch items unchanged after split."""
        original_items = [1, 2, 3]
        batch = Batch(
            tag="root",
            items=list(original_items),
            batch_index=0,
            total_batches=1,
        )
        split_batch_in_half(batch)
        self.assertEqual(batch.items, original_items)


# ============================================================================
# call_complete_with_retry tests
# ============================================================================


class TestCallCompleteWithRetry(unittest.TestCase):
    """Tests for call_complete_with_retry function."""

    def setUp(self):
        self.prompt = MagicMock(spec=PromptBundle)
        self.batch_id = "tag_root_batch_00"

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_network_retry_exhausted(self, mock_sleep, mock_complete):
        """AC: ConnectionError 3 times raises RetryExhaustedError."""
        mock_complete.side_effect = ConnectionError("connection refused")

        with self.assertRaises(RetryExhaustedError) as ctx:
            call_complete_with_retry(
                self.prompt,
                self.batch_id,
                max_network_retries=3,
                backoff_base=0.01,
            )

        self.assertEqual(mock_complete.call_count, 3)
        self.assertIn("exhausted", str(ctx.exception).lower())

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_network_retry_success_after_retries(self, mock_sleep, mock_complete):
        """AC: Fails 2 times, succeeds on 3rd attempt."""
        success = MagicMock()
        mock_complete.side_effect = [
            ConnectionError("fail1"),
            ConnectionError("fail2"),
            success,
        ]

        result = call_complete_with_retry(
            self.prompt,
            self.batch_id,
            max_network_retries=3,
            backoff_base=0.01,
        )

        self.assertIs(result, success)
        self.assertEqual(mock_complete.call_count, 3)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_rate_limit_sleeps_and_retries(self, mock_sleep, mock_complete):
        """AC: RateLimitError triggers 60s sleep then retry."""
        success = MagicMock()
        mock_complete.side_effect = [
            RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429),
                body={},
            ),
            success,
        ]

        result = call_complete_with_retry(
            self.prompt,
            self.batch_id,
            rate_limit_sleep_seconds=60,
        )

        self.assertIs(result, success)
        self.assertEqual(mock_complete.call_count, 2)
        mock_sleep.assert_called_with(60)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_rate_limit_persistent(self, mock_sleep, mock_complete):
        """AC: Persistent RateLimitError propagates after retry."""
        mock_complete.side_effect = RateLimitError(
            "still rate limited",
            response=MagicMock(status_code=429),
            body={},
        )

        with self.assertRaises(RateLimitError):
            call_complete_with_retry(
                self.prompt,
                self.batch_id,
                rate_limit_sleep_seconds=1,
            )

        self.assertEqual(mock_complete.call_count, 2)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_token_limit_raises_token_limit_error(self, mock_sleep, mock_complete):
        """AC: BadRequestError with context length raises TokenLimitError."""
        mock_complete.side_effect = BadRequestError(
            "context length exceeded",
            response=MagicMock(status_code=400),
            body={},
        )

        with self.assertRaises(TokenLimitError) as ctx:
            call_complete_with_retry(self.prompt, self.batch_id)

        self.assertEqual(ctx.exception.batch_id, self.batch_id)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_non_context_bad_request_propagates(self, mock_sleep, mock_complete):
        """AC: BadRequestError without context length propagates."""
        mock_complete.side_effect = BadRequestError(
            "invalid schema",
            response=MagicMock(status_code=400),
            body={},
        )

        with self.assertRaises(BadRequestError):
            call_complete_with_retry(self.prompt, self.batch_id)

        self.assertEqual(mock_complete.call_count, 1)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_non_retryable_exception_propagates(self, mock_sleep, mock_complete):
        """AC: TypeError propagates immediately without retry."""
        mock_complete.side_effect = TypeError("not retryable")

        with self.assertRaises(TypeError):
            call_complete_with_retry(
                self.prompt,
                self.batch_id,
                max_network_retries=3,
                backoff_base=0.01,
            )

        self.assertEqual(mock_complete.call_count, 1)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_retry_logging(self, mock_sleep, mock_complete):
        """AC: Retry count logged per batch for audit."""
        mock_complete.side_effect = [
            ConnectionError("fail1"),
            ConnectionError("fail2"),
            MagicMock(),
        ]

        with self.assertLogs("inference.retry", level="WARNING") as cm:
            call_complete_with_retry(
                self.prompt,
                self.batch_id,
                max_network_retries=3,
                backoff_base=0.01,
            )

        retry_msgs = [m for m in cm.output if "Retry" in m]
        self.assertEqual(len(retry_msgs), 2)
        self.assertIn("Retry attempt 1/3 for batch", retry_msgs[0])
        self.assertIn(self.batch_id, retry_msgs[0])
        self.assertIn("Retry attempt 2/3 for batch", retry_msgs[1])

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_rate_limit_logging(self, mock_sleep, mock_complete):
        """AC: Rate-limit events logged."""
        success = MagicMock()
        mock_complete.side_effect = [
            RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429),
                body={},
            ),
            success,
        ]

        with self.assertLogs("inference.retry", level="WARNING") as cm:
            call_complete_with_retry(
                self.prompt,
                self.batch_id,
                rate_limit_sleep_seconds=1,
            )

        rate_msgs = [m for m in cm.output if "429" in m or "rate limit" in m]
        self.assertTrue(len(rate_msgs) >= 1)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_success_no_retry(self, mock_sleep, mock_complete):
        """AC: Successful call returns immediately with no retry logs."""
        expected = MagicMock()
        mock_complete.return_value = expected

        result = call_complete_with_retry(self.prompt, self.batch_id)

        self.assertIs(result, expected)
        self.assertEqual(mock_complete.call_count, 1)


# ============================================================================
# infer_batch_with_retry tests
# ============================================================================


class TestInferBatchWithRetry(unittest.TestCase):
    """Tests for infer_batch_with_retry convenience wrapper."""

    def setUp(self):
        self.batch = Batch(
            tag="root",
            items=[1, 2, 3, 4],
            batch_index=0,
            total_batches=1,
        )
        self.render_fn = MagicMock(return_value=MagicMock(spec=PromptBundle))

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_success_no_split(self, mock_sleep, mock_complete):
        """AC: Single ChatCompletion returned when no errors."""
        expected = MagicMock()
        mock_complete.return_value = expected

        results = infer_batch_with_retry(self.batch, self.render_fn)

        self.assertEqual(len(results), 1)
        self.assertIs(results[0], expected)
        self.assertEqual(self.render_fn.call_count, 1)
        self.assertEqual(mock_complete.call_count, 1)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_splits_on_token_limit(self, mock_sleep, mock_complete):
        """AC: Batch splits on token limit; each half retried
        independently."""
        success1 = MagicMock()
        success2 = MagicMock()
        call_results = [
            BadRequestError(
                "context length exceeded",
                response=MagicMock(status_code=400),
                body={},
            ),
            success1,
            success2,
        ]

        def side_effect(*args, **kwargs):
            r = call_results.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r

        mock_complete.side_effect = side_effect

        results = infer_batch_with_retry(
            self.batch,
            self.render_fn,
            backoff_base=0.01,
        )

        self.assertEqual(len(results), 2)
        self.assertIs(results[0], success1)
        self.assertIs(results[1], success2)

        # render_fn called 3 times: original + half1 + half2
        self.assertEqual(self.render_fn.call_count, 3)
        first_batch = self.render_fn.call_args_list[0].args[0]
        second_batch = self.render_fn.call_args_list[1].args[0]
        third_batch = self.render_fn.call_args_list[2].args[0]
        self.assertEqual(len(first_batch.items), 4)
        self.assertEqual(len(second_batch.items), 2)
        self.assertEqual(len(third_batch.items), 2)

        # complete called 3 times: 1 failure + 2 successes
        self.assertEqual(mock_complete.call_count, 3)

    @patch("inference.retry.complete")
    @patch("time.sleep", return_value=None)
    def test_network_error_before_split(self, mock_sleep, mock_complete):
        """AC: Network error on full batch produces RetryExhaustedError."""
        mock_complete.side_effect = ConnectionError("connection refused")

        with self.assertRaises(RetryExhaustedError):
            infer_batch_with_retry(
                self.batch,
                self.render_fn,
                max_network_retries=2,
                backoff_base=0.01,
            )

        self.assertEqual(mock_complete.call_count, 2)


if __name__ == "__main__":
    unittest.main()
