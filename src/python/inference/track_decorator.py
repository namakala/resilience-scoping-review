"""Decorator for automatic token tracking of LLM calls.

Provides :func:`track_tokens`, a decorator that intercepts the return
value of a Groq ``complete()`` call, extracts usage information, and
records it via the :class:`inference.tracking.TokenTracker` singleton.
"""

import functools
from typing import Any, Callable

from .tracking import get_tracker

__all__ = ["track_tokens"]


def track_tokens(stage_name: str) -> Callable:
    """Decorator that automatically records token usage from an LLM call.

    The wrapped function **must** return an object with a ``.usage``
    attribute that has ``.prompt_tokens`` and ``.completion_tokens``
    (i.e. a Groq ``ChatCompletion`` object). Usage data is recorded
    via :func:`get_tracker`.

    Usage::

        @track_tokens("code_inference")
        def infer_batch(prompt, batch_id="unknown"):
            return complete(prompt)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            usage = getattr(result, "usage", None)
            if usage is not None:
                tracker = get_tracker()
                batch_id = kwargs.get("batch_id", "unknown")
                tracker.record(
                    stage=stage_name,
                    batch_id=batch_id,
                    input_tokens=getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                )
            return result

        return wrapper

    return decorator
