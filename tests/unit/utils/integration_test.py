"""Integration tests combining retry and circuit breaker."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src/python to sys.path so utils can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.circuit_breaker import make_circuit_breaker  # noqa: E402
from utils.exceptions import CircuitBreakerOpenError  # noqa: E402
from utils.retry import make_retry  # noqa: E402


class TestErrorHandlingIntegration(unittest.TestCase):
    """Integration tests combining retry and circuit breaker."""

    @patch("time.sleep", return_value=None)
    def test_retry_with_circuit_breaker_combination(self, mock_sleep):
        """Verify @make_retry and @make_circuit_breaker can be stacked."""
        call_count = 0
        failure_threshold = 2
        max_attempts = 3

        @make_retry(max_attempts=max_attempts, backoff=1, retry_on=(ConnectionError,))
        @make_circuit_breaker(failure_threshold=failure_threshold, reset_timeout=10)
        def combined_service():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("combined failure")

        # Circuit opens after 2 failures; third attempt triggers fallback.
        # Retry will see CircuitBreakerOpenError (not retryable) and propagate.
        with self.assertRaises(CircuitBreakerOpenError):
            combined_service()


if __name__ == "__main__":
    unittest.main()
