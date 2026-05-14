"""Utility modules for the resilience scoping review pipeline.

Provides error handling utilities:
exceptions, retry, circuit breaker, and graceful shutdown.
"""

from .circuit_breaker import make_circuit_breaker
from .exceptions import (
    CircuitBreakerOpenError,
    ConfigurationError,
    GroqAPIError,
    ParseError,
    RetryExhaustedError,
    ShutdownRequestedError,
)
from .graceful_shutdown import graceful_shutdown
from .logging import get_logger
from .retry import make_retry

__all__ = [
    "get_logger",
    "GroqAPIError",
    "RetryExhaustedError",
    "CircuitBreakerOpenError",
    "ShutdownRequestedError",
    "ConfigurationError",
    "ParseError",
    "make_retry",
    "make_circuit_breaker",
    "graceful_shutdown",
]
