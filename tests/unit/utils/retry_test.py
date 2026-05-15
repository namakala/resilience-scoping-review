"""Tests for @make_retry decorator."""

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src/python to sys.path so utils can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.exceptions import RetryExhaustedError  # noqa: E402
from utils.retry import make_retry  # noqa: E402

# ============================================================================
# Helper Fixtures
# ============================================================================


def get_logger() -> logging.Logger:
    return logging.getLogger("test.retry")


# ============================================================================
# Retry Decorator Tests
# ============================================================================


class TestRetryDecorator(unittest.TestCase):
    """Tests for @make_retry decorator."""

    def setUp(self):
        self.logger = get_logger()
        self.logger.handlers = []
        self.logger.setLevel(logging.DEBUG)

    @patch("time.sleep", return_value=None)
    def test_retry_exponential_backoff_delays(self, mock_sleep):
        """Verify exponential backoff delay sequence."""
        attempts = 0
        max_attempts = 4
        backoff = 1.0

        @make_retry(max_attempts=max_attempts, backoff=backoff, retry_on=(ValueError,))
        def flaky_func():
            nonlocal attempts
            attempts += 1
            if attempts < max_attempts:
                raise ValueError("Transient error")
            return "success"

        result = flaky_func()
        self.assertEqual(result, "success")
        self.assertEqual(attempts, max_attempts)

        # Verify backoff sequence: 1s, 2s, 4s (min=backoff, max calculated)
        expected_delays = [
            backoff * (2**i) for i in range(max_attempts - 1)  # i = 0,1,2 => 1,2,4
        ]
        actual_delays = [call_args[0][0] for call_args in mock_sleep.call_args_list]
        self.assertEqual(actual_delays, expected_delays)

    @patch("time.sleep", return_value=None)
    def test_retry_logs_attempts(self, mock_sleep):
        """Verify retry attempts are logged."""

        @make_retry(max_attempts=2, backoff=1, retry_on=(ValueError,))
        def failing_func():
            raise ValueError("test error")

        with self.assertLogs(level="WARNING") as cm:
            try:
                failing_func()
            except RetryExhaustedError:
                pass

        self.assertTrue(any("Retry attempt" in msg for msg in cm.output))

    @patch("time.sleep", return_value=None)
    def test_retry_max_attempts_exhausted_raises(self, mock_sleep):
        """Verify RetryExhaustedError raised after exhausting retries."""
        call_count = 0
        max_attempts = 3

        @make_retry(max_attempts=max_attempts, backoff=1, retry_on=(RuntimeError,))
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Permanent failure")

        with self.assertRaises(RetryExhaustedError) as cm:
            always_fails()
        self.assertEqual(call_count, max_attempts)
        self.assertIn("exhausted", str(cm.exception).lower())

    @patch("time.sleep", return_value=None)
    def test_retry_only_specified_exceptions_trigger_retry(self, mock_sleep):
        """Verify only configured exception types cause retries."""
        call_count = 0

        @make_retry(max_attempts=3, backoff=1, retry_on=(ValueError,))
        def mixed_exceptions():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Retryable")
            elif call_count == 2:
                raise TypeError("Not retryable")
            return "success"

        with self.assertRaises(TypeError):
            mixed_exceptions()
        self.assertEqual(call_count, 2)

    @patch("time.sleep", return_value=None)
    def test_retry_success_after_transient_failures(self, mock_sleep):
        """Verify function returns successfully after retries."""
        call_count = 0

        @make_retry(max_attempts=5, backoff=1, retry_on=(ConnectionError,))
        def eventually_works():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network glitch")
            return "ok"

        result = eventually_works()
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 3)

    def test_retry_parameter_validation(self):
        """Verify parameter validation raises ValueError on invalid inputs."""
        with self.assertRaises(ValueError):
            make_retry(max_attempts=0, backoff=1)
        with self.assertRaises(ValueError):
            make_retry(max_attempts=-1, backoff=1)
        with self.assertRaises(ValueError):
            make_retry(max_attempts=3, backoff=0)
        with self.assertRaises(ValueError):
            make_retry(max_attempts=3, backoff=-2)

    @patch("time.sleep", return_value=None)
    def test_retry_with_custom_exception_tuple(self, mock_sleep):
        """Verify custom exception tuple works."""

        class CustomError(Exception):
            pass

        @make_retry(max_attempts=2, backoff=1, retry_on=(CustomError,))
        def custom_failure():
            raise CustomError("custom")

        with self.assertRaises(RetryExhaustedError):
            custom_failure()

    @patch("time.sleep", return_value=None)
    def test_label_parameter_appears_in_logs_and_error(self, mock_sleep):
        """Verify label replaces func.__name__ in logs and error
        messages."""

        exc = None
        with self.assertLogs(level="WARNING") as logs:
            try:

                @make_retry(
                    max_attempts=2,
                    backoff=1,
                    retry_on=(ValueError,),
                    label="my_batch",
                )
                def failing():
                    raise ValueError("test")

                failing()
            except RetryExhaustedError as e:
                exc = e

        self.assertIsNotNone(exc)
        self.assertIn("my_batch", str(exc))
        self.assertTrue(any("my_batch" in msg for msg in logs.output))


if __name__ == "__main__":
    unittest.main()
