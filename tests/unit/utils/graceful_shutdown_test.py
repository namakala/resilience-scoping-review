"""Tests for graceful_shutdown context manager."""

import logging
import signal
import sys
import unittest
from pathlib import Path

# Add src/python to sys.path so utils can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.graceful_shutdown import graceful_shutdown  # noqa: E402

# ============================================================================
# Helper Fixtures
# ============================================================================


def get_logger() -> logging.Logger:
    return logging.getLogger("test.graceful_shutdown")


# ============================================================================
# Graceful Shutdown Context Manager Tests
# ============================================================================


class TestGracefulShutdown(unittest.TestCase):
    """Tests for graceful_shutdown context manager."""

    def test_signal_handler_invoked_on_sigint(self):
        """SIGINT triggers shutdown handler."""
        cleanup_called = False

        def cleanup():
            nonlocal cleanup_called
            cleanup_called = True

        gs = graceful_shutdown(cleanup)
        gs.__enter__()

        with self.assertRaises(SystemExit) as cm:
            gs._signal_handler(signal.SIGINT, None)

        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(cleanup_called)

    def test_signal_handler_invoked_on_sigterm(self):
        """SIGTERM triggers shutdown handler."""
        cleanup_called = False

        def cleanup():
            nonlocal cleanup_called
            cleanup_called = True

        gs = graceful_shutdown(cleanup)
        gs.__enter__()

        with self.assertRaises(SystemExit) as cm:
            gs._signal_handler(signal.SIGTERM, None)

        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(cleanup_called)

    def test_cleanup_callbacks_executed_in_lifo_order(self):
        """Cleanup callbacks run in reverse registration order (LIFO)."""
        execution_order = []

        def callback1():
            execution_order.append("first")

        def callback2():
            execution_order.append("second")

        def callback3():
            execution_order.append("third")

        gs = graceful_shutdown([callback1, callback2, callback3])
        gs.__enter__()

        with self.assertRaises(SystemExit):
            gs._signal_handler(signal.SIGINT, None)

        self.assertEqual(execution_order, ["third", "second", "first"])

    def test_multiple_signals_are_idempotent(self):
        """Subsequent signals after first are ignored."""
        cleanup_calls = []

        def cleanup():
            cleanup_calls.append(1)

        gs = graceful_shutdown(cleanup)
        gs.__enter__()

        try:
            gs._signal_handler(signal.SIGINT, None)
        except SystemExit:
            pass

        self.assertEqual(len(cleanup_calls), 1)

        # Second signal ignored
        gs._signal_handler(signal.SIGTERM, None)
        self.assertEqual(len(cleanup_calls), 1)

    def test_cleanup_callback_exceptions_are_caught_and_logged(self):
        """Exceptions in cleanup callbacks are logged but do not crash shutdown."""

        def good_cleanup():
            pass

        def bad_cleanup():
            raise RuntimeError("cleanup failed")

        gs = graceful_shutdown([good_cleanup, bad_cleanup])
        gs.__enter__()

        # Note: logger name is 'utils.graceful_shutdown' due to __name__ in the module
        with (
            self.assertRaises(SystemExit),
            self.assertLogs("utils.graceful_shutdown", level="ERROR") as cm,
        ):
            gs._signal_handler(signal.SIGINT, None)

        # Verify error was logged
        self.assertTrue(
            any("Cleanup callback bad_cleanup failed" in msg for msg in cm.output)
        )

    def test_context_manager_restores_original_handlers(self):
        """Original signal handlers are restored on context exit."""
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        gs = graceful_shutdown()
        gs.__enter__()

        self.assertNotEqual(signal.getsignal(signal.SIGINT), original_sigint)
        self.assertNotEqual(signal.getsignal(signal.SIGTERM), original_sigterm)

        # Exit without shutdown
        gs.__exit__(None, None, None)

        self.assertEqual(signal.getsignal(signal.SIGINT), original_sigint)
        self.assertEqual(signal.getsignal(signal.SIGTERM), original_sigterm)

    def test_re_entry_protection(self):
        """__enter__ does nothing if shutdown already in progress."""
        cleanup_count = 0

        def cleanup():
            nonlocal cleanup_count
            cleanup_count += 1

        gs = graceful_shutdown(cleanup)
        gs.__enter__()

        try:
            gs._signal_handler(signal.SIGINT, None)
        except SystemExit:
            pass

        self.assertTrue(gs._shutdown_in_progress)
        self.assertEqual(cleanup_count, 1)

        # Exiting after shutdown is safe
        gs.__exit__(None, None, None)
        self.assertEqual(cleanup_count, 1)

    def test_empty_cleanup_callbacks(self):
        """Works with no callbacks."""
        gs = graceful_shutdown()
        gs.__enter__()
        with self.assertRaises(SystemExit):
            gs._signal_handler(signal.SIGINT, None)

    def test_single_callable_cleanup(self):
        """Single callable (not list) is accepted."""
        called = False

        def cleanup():
            nonlocal called
            called = True

        gs = graceful_shutdown(cleanup)
        gs.__enter__()
        with self.assertRaises(SystemExit):
            gs._signal_handler(signal.SIGTERM, None)

        self.assertTrue(called)


if __name__ == "__main__":
    unittest.main()
