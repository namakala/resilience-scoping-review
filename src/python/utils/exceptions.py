"""Custom exceptions for error handling resilience patterns.

Provides domain-specific exception types for retry exhaustion,
circuit breaker open state, and graceful shutdown requests.
"""

from typing import Any

__all__ = [
    "GroqAPIError",
    "RetryExhaustedError",
    "CircuitBreakerOpenError",
    "ShutdownRequestedError",
    "StateError",
]


class GroqAPIError(Exception):
    """Raised when Groq API call fails (network, rate-limit, or server error)."""

    def __init__(self, message: str = "", *args: Any) -> None:
        super().__init__(message or "Groq API call failed", *args)


class RetryExhaustedError(Exception):
    """Raised when retry decorator exhausts all attempts without success."""

    def __init__(self, message: str = "", *args: Any) -> None:
        super().__init__(
            message or "Retry attempts exhausted without successful return",
            *args,
        )


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and call is blocked."""

    def __init__(
        self,
        message: str = "",
        failure_count: int = 0,
        reset_timeout: float = 0.0,
    ) -> None:
        if not message and failure_count:
            message = (
                f"Circuit breaker OPEN (failures={failure_count}, "
                f"reset in {reset_timeout:.0f}s)"
            )
        super().__init__(message or "Circuit breaker is open", *())


class ShutdownRequestedError(KeyboardInterrupt):
    """Raised when graceful shutdown is triggered by SIGINT/SIGTERM."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Shutdown requested via signal handler")


class StateError(Exception):
    """Raised when workflow state operations fail
    (validation, corruption, DB errors)."""

    def __init__(self, message: str = "", *args: Any) -> None:
        super().__init__(message or "Workflow state error", *args)
