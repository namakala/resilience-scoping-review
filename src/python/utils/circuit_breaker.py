"""Circuit breaker decorator for fail-fast error handling.

Prevents cascading failures by tracking consecutive failures and
temporarily blocking calls when a threshold is exceeded. Implements
the classic circuit breaker pattern with CLOSED, OPEN, and HALF_OPEN states.

Usage:
    from utils.circuit_breaker import make_circuit_breaker

    @make_circuit_breaker(failure_threshold=5, reset_timeout=60)
    def external_service_call():
        ...
"""

import logging
import threading
from functools import wraps
from typing import Any, Callable, Optional

from circuitbreaker import CircuitBreaker as _CircuitBreaker
from circuitbreaker import CircuitBreakerError

from .exceptions import CircuitBreakerOpenError

__all__ = ["make_circuit_breaker"]


def make_circuit_breaker(
    failure_threshold: int = 5,
    reset_timeout: float = 60.0,
    logger: Optional[logging.Logger] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory that wraps function with circuit breaker pattern.

    Circuit states:
      - CLOSED: Normal operation; failures increment counter.
      - OPEN: After threshold failures; calls immediately raise CircuitBreakerOpenError.
      - HALF-OPEN: After reset_timeout; one test call allowed.
        Success → CLOSED, Failure → OPEN again.

    Args:
        failure_threshold: Number of consecutive failures before opening (must be > 0).
        reset_timeout: Seconds in OPEN state before attempting HALF_OPEN (must be > 0).
        logger: Optional logger for state transitions.

    Returns:
        Decorated function with circuit breaker protection.

    Raises:
        ValueError: If failure_threshold <= 0 or reset_timeout <= 0.

    Example:
        >>> @make_circuit_breaker(failure_threshold=3, reset_timeout=30)
        ... def unreliable_api():
        ...     ...
    """
    if failure_threshold <= 0:
        raise ValueError(f"failure_threshold must be > 0, got {failure_threshold}")
    if reset_timeout <= 0:
        raise ValueError(f"reset_timeout must be > 0, got {reset_timeout}")

    # Use a lock for thread-safe state transitions
    _lock = threading.Lock()

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal _lock

        # Define fallback inside decorator to capture func
        def fallback_function(*args: Any, **kwargs: Any) -> Any:
            raise CircuitBreakerOpenError(
                f"Circuit breaker OPEN for '{func.__name__}'. "
                f"Failure threshold: {failure_threshold}, "
                f"reset timeout: {reset_timeout}s"
            )

        breaker = _CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=reset_timeout,
            expected_exception=Exception,
            name=func.__name__,
            fallback_function=fallback_function,
        )
        _logger = logger or logging.getLogger(func.__module__)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _lock:
                state_before = breaker.state

            try:
                result = breaker(func)(*args, **kwargs)
                with _lock:
                    state_after = breaker.state
                if state_before != state_after:
                    _logger.info(
                        "Circuit state transition for %s: %s → %s",
                        func.__name__,
                        state_before,
                        state_after,
                    )
                return result
            except CircuitBreakerError:
                with _lock:
                    state_after = breaker.state
                _logger.warning(
                    "Circuit breaker active for %s: state=%s, failures=%d, "
                    "next recovery=%ds",
                    func.__name__,
                    state_after,
                    breaker.failure_count,
                    breaker.open_remaining if breaker.opened else 0,
                )
                raise CircuitBreakerOpenError(
                    f"Circuit OPEN for '{func.__name__}'. "
                    f"Failure count: {breaker.failure_count}, "
                    f"Reset in {breaker.open_remaining:.0f}s"
                ) from None

        # Expose state inspection methods for testing/diagnostics
        wrapper.circuit_state = lambda: breaker.state  # type: ignore[attr-defined]
        wrapper.circuit_failure_count = (  # type: ignore[attr-defined]
            lambda: breaker.failure_count
        )
        wrapper.circuit_open_remaining = (  # type: ignore[attr-defined]
            lambda: breaker.open_remaining if breaker.opened else 0
        )
        wrapper.circuit_reset = lambda: breaker.reset()  # type: ignore[attr-defined]
        wrapper._breaker = breaker  # type: ignore[attr-defined]

        return wrapper

    return decorator
