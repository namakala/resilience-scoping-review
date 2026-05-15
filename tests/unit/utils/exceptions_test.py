"""Unit tests for error handling exception classes.

Verifies correct instantiation and inheritance of domain-specific
exceptions.
"""

import sys
import unittest
from pathlib import Path

# Add src/python to sys.path so utils can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.exceptions import (  # noqa: E402
    CircuitBreakerOpenError,
    GroqAPIError,
    RetryExhaustedError,
    ShutdownRequestedError,
)


class TestExceptions(unittest.TestCase):
    """Tests for custom exception classes."""

    def test_groq_api_error(self):
        """Verify GroqAPIError instantiation and message."""
        exc = GroqAPIError("custom error")
        self.assertEqual(str(exc), "custom error")

        exc_default = GroqAPIError()
        self.assertEqual(str(exc_default), "Groq API call failed")

    def test_retry_exhausted_error(self):
        """Verify RetryExhaustedError instantiation and message."""
        exc = RetryExhaustedError("exhausted")
        self.assertEqual(str(exc), "exhausted")

        exc_default = RetryExhaustedError()
        self.assertIn("exhausted", str(exc_default).lower())

    def test_circuit_breaker_open_error(self):
        """Verify CircuitBreakerOpenError instantiation and messages."""
        exc = CircuitBreakerOpenError("manual error")
        self.assertEqual(str(exc), "manual error")

        # Test default message with provided metadata
        exc_meta = CircuitBreakerOpenError(failure_count=5, reset_timeout=30.0)
        self.assertIn("failures=5", str(exc_meta))
        self.assertIn("reset in 30s", str(exc_meta))

    def test_shutdown_requested_error(self):
        """Verify ShutdownRequestedError inheritance and message."""
        exc = ShutdownRequestedError("shutdown now")
        self.assertIsInstance(exc, KeyboardInterrupt)
        self.assertEqual(str(exc), "shutdown now")

        exc_default = ShutdownRequestedError()
        self.assertIn("Shutdown requested", str(exc_default))


if __name__ == "__main__":
    unittest.main()
