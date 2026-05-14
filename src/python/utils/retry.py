"""Retry decorator with exponential backoff for transient failures.

Provides a decorator factory that wraps functions with retry logic,
using tenacity for exponential backoff and configurable exception filtering.
Used primarily for Groq API calls and network operations.

Usage:
    from utils.retry import make_retry

    @make_retry(max_attempts=3, backoff=2.0, retry_on=(TimeoutError, ConnectionError))
    def call_api():
        ...
"""

import logging
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type

from tenacity import RetryCallState
from tenacity import RetryError as TenacityRetryError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import GroqAPIError, RetryExhaustedError

__all__ = ["make_retry"]


def make_retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    retry_on: Tuple[Type[BaseException], ...] = (
        TimeoutError,
        ConnectionError,
        GroqAPIError,
    ),
    logger: Optional[logging.Logger] = None,
    label: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory that retries a function with exponential backoff.

    Retries the wrapped function when exceptions from ``retry_on`` are raised.
    Delays increase exponentially: backoff, 2*backoff, 4*backoff, etc.
    Retries stop after ``max_attempts`` total calls (initial + retries).

    Args:
        max_attempts: Maximum number of attempts (must be > 0).
        backoff: Base backoff multiplier in seconds (must be > 0).
        retry_on: Tuple of exception types that trigger a retry.
        logger: Optional logger for retry audit trail.
        label: Override for ``func.__name__`` in logs and error messages.

    Returns:
        Decorated function with retry logic.

    Raises:
        ValueError: If max_attempts <= 0 or backoff <= 0.

    Example:
        >>> @make_retry(max_attempts=3, backoff=1.0, retry_on=(ValueError,))
        ... def flaky():
        ...     ...
    """
    if max_attempts <= 0:
        raise ValueError(f"max_attempts must be > 0, got {max_attempts}")
    if backoff <= 0:
        raise ValueError(f"backoff must be > 0, got {backoff}")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _name = label or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _logger = logger or logging.getLogger(func.__module__)

            def before_sleep_callback(retry_state: RetryCallState) -> None:
                attempt = retry_state.attempt_number
                last_exc = retry_state.outcome.exception()
                _logger.warning(
                    "Retry attempt %d/%d for %s after error: %s",
                    attempt,
                    max_attempts,
                    _name,
                    type(last_exc).__name__ if last_exc else "unknown",
                )

            try:
                return retry(
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(
                        multiplier=backoff,
                        min=backoff,
                        max=backoff * (2 ** (max_attempts - 1)),
                    ),
                    retry=retry_if_exception_type(retry_on),
                    before_sleep=before_sleep_callback,
                )(func)(*args, **kwargs)
            except TenacityRetryError as e:
                raise RetryExhaustedError(
                    f"Function {_name} exhausted after {max_attempts} attempts"
                ) from e.__cause__

        return wrapper

    return decorator
