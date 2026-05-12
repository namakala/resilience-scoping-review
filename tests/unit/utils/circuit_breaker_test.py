"""Tests for @make_circuit_breaker decorator."""

import logging
import sys
import time
import unittest
from pathlib import Path

# Add src/python to sys.path so utils can be imported
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.circuit_breaker import make_circuit_breaker  # noqa: E402
from utils.exceptions import CircuitBreakerOpenError  # noqa: E402

# ============================================================================
# Helper Fixtures
# ============================================================================


def get_logger() -> logging.Logger:
    return logging.getLogger("test.circuit_breaker")


# ============================================================================
# Circuit Breaker Decorator Tests
# ============================================================================


class TestCircuitBreakerDecorator(unittest.TestCase):
    """Tests for @make_circuit_breaker decorator."""

    def setUp(self):
        self.logger = get_logger()
        self.logger.handlers = []
        self.logger.setLevel(logging.DEBUG)

    def test_circuit_parameter_validation(self):
        """Verify parameter validation raises ValueError on invalid inputs."""
        with self.assertRaises(ValueError):
            make_circuit_breaker(failure_threshold=0, reset_timeout=1)
        with self.assertRaises(ValueError):
            make_circuit_breaker(failure_threshold=-1, reset_timeout=1)
        with self.assertRaises(ValueError):
            make_circuit_breaker(failure_threshold=3, reset_timeout=0)
        with self.assertRaises(ValueError):
            make_circuit_breaker(failure_threshold=3, reset_timeout=-5)

    def test_circuit_opens_after_failure_threshold(self):
        """Circuit opens after failure_threshold consecutive failures."""
        threshold = 3
        call_count = 0

        @make_circuit_breaker(failure_threshold=threshold, reset_timeout=10)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        # Fail 'threshold' times; each should raise ConnectionError
        for _ in range(threshold):
            with self.assertRaises(ConnectionError):
                always_fails()

        # Circuit is now OPEN
        self.assertEqual(always_fails.circuit_state(), "open")
        self.assertEqual(call_count, threshold)

    def test_circuit_open_blocks_calls_immediately(self):
        """When circuit is OPEN, further calls raise
        CircuitBreakerOpenError without executing function."""
        threshold = 2
        execution_count = 0

        @make_circuit_breaker(failure_threshold=threshold, reset_timeout=10)
        def always_fails():
            nonlocal execution_count
            execution_count += 1
            raise ConnectionError("fail")

        # Trigger open
        for _ in range(threshold):
            with self.assertRaises(ConnectionError):
                always_fails()

        # Next call blocked; function not executed
        with self.assertRaises(CircuitBreakerOpenError):
            always_fails()
        self.assertEqual(execution_count, threshold)

    def test_circuit_state_inspection(self):
        """Verify exposed state inspection methods work."""

        @make_circuit_breaker(failure_threshold=2, reset_timeout=10)
        def test_func():
            if test_func.failures < 2:
                test_func.failures += 1
                raise ConnectionError("fail")
            return "ok"

        test_func.failures = 0

        # Initially closed
        self.assertEqual(test_func.circuit_state(), "closed")

        # First failure - still closed
        with self.assertRaises(ConnectionError):
            test_func()
        self.assertEqual(test_func.circuit_state(), "closed")

        # Second failure - opens
        with self.assertRaises(ConnectionError):
            test_func()
        self.assertEqual(test_func.circuit_state(), "open")

    def test_circuit_failure_count_resets_on_success(self):
        """After a successful call, failure count resets to 0."""

        @make_circuit_breaker(failure_threshold=3, reset_timeout=10)
        def fails_then_succeeds():
            if fails_then_succeeds.failures < 2:
                fails_then_succeeds.failures += 1
                raise ConnectionError("fail")
            return "ok"

        fails_then_succeeds.failures = 0

        # Two failures
        for _ in range(2):
            with self.assertRaises(ConnectionError):
                fails_then_succeeds()

        # Still closed; failure count = 2
        self.assertEqual(fails_then_succeeds.circuit_state(), "closed")
        self.assertEqual(fails_then_succeeds.circuit_failure_count(), 2)

        # Success resets count
        result = fails_then_succeeds()
        self.assertEqual(result, "ok")
        self.assertEqual(fails_then_succeeds.circuit_failure_count(), 0)

    def test_circuit_manual_reset(self):
        """Manual reset closes circuit and clears failure count."""
        threshold = 2

        @make_circuit_breaker(failure_threshold=threshold, reset_timeout=10)
        def test_func():
            raise ConnectionError("fail")

        # Fail to open
        for _ in range(threshold):
            with self.assertRaises(ConnectionError):
                test_func()

        self.assertEqual(test_func.circuit_state(), "open")

        # Manual reset
        test_func.circuit_reset()
        self.assertEqual(test_func.circuit_state(), "closed")
        self.assertEqual(test_func.circuit_failure_count(), 0)

    def test_circuit_half_open_after_timeout(self):
        """After reset_timeout, circuit allows a test call (HALF_OPEN)."""
        threshold = 2
        reset_timeout = 0.2  # seconds

        @make_circuit_breaker(failure_threshold=threshold, reset_timeout=reset_timeout)
        def always_fails():
            raise ConnectionError("fail")

        # Fail to open
        for _ in range(threshold):
            with self.assertRaises(ConnectionError):
                always_fails()

        self.assertEqual(always_fails.circuit_state(), "open")

        # Wait for timeout
        time.sleep(reset_timeout + 0.1)

        # Next call is allowed (half-open); it fails again, causing circuit to reopen
        with self.assertRaises(ConnectionError):
            always_fails()
        self.assertEqual(always_fails.circuit_state(), "open")

    def test_half_open_success_closes_circuit(self):
        """A successful call in HALF_OPEN state closes the circuit."""
        threshold = 2
        reset_timeout = 0.2

        @make_circuit_breaker(failure_threshold=threshold, reset_timeout=reset_timeout)
        def intermittent():
            if intermittent.failures < 2:
                intermittent.failures += 1
                raise ConnectionError("fail")
            return "recovered"

        intermittent.failures = 0

        # Fail twice to open
        for _ in range(threshold):
            with self.assertRaises(ConnectionError):
                intermittent()

        self.assertEqual(intermittent.circuit_state(), "open")

        # Wait for half-open
        time.sleep(reset_timeout + 0.1)

        # Next call succeeds, closing circuit
        result = intermittent()
        self.assertEqual(result, "recovered")
        self.assertEqual(intermittent.circuit_state(), "closed")

    def test_circuit_open_remaining(self):
        """circuit_open_remaining returns seconds until half-open attempt."""

        @make_circuit_breaker(failure_threshold=1, reset_timeout=5)
        def test_func():
            raise ConnectionError("fail")

        # Fail once to open
        with self.assertRaises(ConnectionError):
            test_func()
        self.assertEqual(test_func.circuit_state(), "open")

        remaining = test_func.circuit_open_remaining()
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 5)


if __name__ == "__main__":
    unittest.main()
