"""Graceful shutdown context manager for clean signal handling.

Captures SIGINT (Ctrl-C) and SIGTERM signals, runs registered cleanup
callbacks in LIFO order, logs the shutdown reason, then exits cleanly.
Original signal handlers are restored on context exit.

Usage:
    from utils.graceful_shutdown import graceful_shutdown

    def cleanup():
        save_state()
        close_db()

    with graceful_shutdown(cleanup):
        while running:
            process_work()
"""

import logging
import signal
import sys
import threading
from typing import Any, Callable, List, Optional

__all__ = ["graceful_shutdown"]


class graceful_shutdown:
    """Context manager that handles SIGINT/SIGTERM for clean shutdown.

    Captures Ctrl-C and kill signals, runs registered cleanup callbacks in
    LIFO (stack) order, logs the shutdown reason, then exits the process.
    Original signal handlers are restored on context exit.

    Attributes:
        cleanup_callbacks: List of callables with no arguments to execute on shutdown.

    Example:
        >>> def cleanup():
        ...     save_state()
        ...     close_db()
        >>> with graceful_shutdown(cleanup):
        ...     while running:
        ...         process_work()

    Args:
        cleanup_callbacks: Single callable or list of callables to run on shutdown.
    """

    def __init__(
        self,
        cleanup_callbacks: Optional[
            List[Callable[[], None]] | Callable[[], None]
        ] = None,
    ) -> None:
        # Normalize to list
        if cleanup_callbacks is None:
            self._cleanup_callbacks: List[Callable[[], None]] = []
        elif callable(cleanup_callbacks):
            self._cleanup_callbacks = [cleanup_callbacks]
        else:
            self._cleanup_callbacks = list(cleanup_callbacks)

        self._shutdown_event: threading.Event = threading.Event()
        self._lock = threading.Lock()
        self._shutdown_in_progress = False
        self._original_sigint: Any = None  # signal handler type varies
        self._original_sigterm: Any = None
        self._logger = logging.getLogger(__name__)

    def __enter__(self) -> "graceful_shutdown":
        """Register signal handlers. Restore previous handlers if already active."""
        with self._lock:
            if self._shutdown_in_progress:
                # Already shutting down; don't re-register
                return self

            # Save original handlers
            self._original_sigint = signal.getsignal(signal.SIGINT)
            self._original_sigterm = signal.getsignal(signal.SIGTERM)

            # Register our handlers
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

            self._logger.debug("Graceful shutdown handler registered")
            return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Restore original signal handlers."""
        with self._lock:
            if self._original_sigint is not None:
                signal.signal(signal.SIGINT, self._original_sigint)
                self._original_sigint = None
            if self._original_sigterm is not None:
                signal.signal(signal.SIGTERM, self._original_sigterm)
                self._original_sigterm = None
            self._shutdown_in_progress = False
            self._logger.debug("Original signal handlers restored")
        # No exception suppression

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle incoming signals: run cleanup callbacks, exit cleanly."""
        with self._lock:
            if self._shutdown_event.is_set():
                # Already shutting down; ignore subsequent signals
                self._logger.debug(
                    "Shutdown already in progress; ignoring duplicate signal"
                )
                return
            self._shutdown_event.set()
            self._shutdown_in_progress = True

        signal_name = signal.Signals(signum).name
        self._logger.info("Received %s; initiating graceful shutdown", signal_name)

        # Execute cleanup callbacks in LIFO order (last registered, first executed)
        for callback in reversed(self._cleanup_callbacks):
            try:
                self._logger.debug("Running cleanup callback: %s", callback.__name__)
                callback()
            except Exception as exc:
                self._logger.error(
                    "Cleanup callback %s failed: %s",
                    callback.__name__,
                    exc,
                    exc_info=True,
                )

        self._logger.info("Graceful shutdown complete; exiting with code 0")
        sys.exit(0)
