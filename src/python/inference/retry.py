"""Retry and rate-limit handling for Groq batch inference.

Three-tier retry for the :func:`complete` function:

1. Network errors (timeout, connection) --- exponential backoff via ``make_retry``.
2. HTTP 429 (rate limit) --- sleep 60s --- retry once.
3. Token limit (context-length BadRequestError) --- raises :class:`TokenLimitError`
   so the caller can split the batch and retry each half.

Usage:
    from inference.retry import (
        TokenLimitError,
        call_complete_with_retry,
        infer_batch_with_retry,
    )

    # Low-level: handle token-limit on your own
    try:
        reply = call_complete_with_retry(prompt, batch_id="tag_root_batch_00")
    except TokenLimitError:
        ...

    # High-level: everything handled automatically
    replies = infer_batch_with_retry(batch, render_code_prompt)
"""

import logging
import time
from typing import Callable

from groq import APIConnectionError, APITimeoutError, BadRequestError, RateLimitError
from utils.exceptions import GroqAPIError
from utils.logging import get_logger
from utils.retry import make_retry

from .batching import Batch, split_batch_in_half
from .groq_client import complete
from .prompts import PromptBundle

__all__ = [
    "TokenLimitError",
    "call_complete_with_retry",
    "infer_batch_with_retry",
]

logger = get_logger(__name__)

_NETWORK_ERRORS = (
    TimeoutError,
    ConnectionError,
    GroqAPIError,
    APITimeoutError,
    APIConnectionError,
)


class TokenLimitError(Exception):
    """Raised when Groq returns a context-length error.

    The batch must be split in half and each half retried independently.
    The ``batch_id`` attribute identifies the failing batch.
    """

    def __init__(self, batch_id: str = "", *args: object) -> None:
        msg = (
            f"Token limit exceeded for batch {batch_id}"
            if batch_id
            else "Token limit exceeded"
        )
        super().__init__(msg, *args)
        self.batch_id = batch_id


def call_complete_with_retry(
    prompt: PromptBundle,
    batch_id: str,
    model: str | None = None,
    temperature: float = 0.0,
    response_format: dict | None = None,
    max_network_retries: int = 3,
    backoff_base: float = 2.0,
    rate_limit_sleep_seconds: int = 60,
):
    """Call ``complete()`` with retry for network errors and rate limits.

    Three-tier retry:

    1. Network errors --- exponential backoff (2s, 4s, 8s default, up to
       ``max_network_retries`` attempts) via :func:`utils.retry.make_retry`.
    2. HTTP 429 --- sleep ``rate_limit_sleep_seconds`` (default 60) then
       retry once.
    3. Token limit --- raises :class:`TokenLimitError`.

    Returns
    -------
    ChatCompletion
        The Groq API response.

    Raises
    ------
    TokenLimitError
        On context-length error (caller should split batch and retry).
    RetryExhaustedError
        After ``max_network_retries`` network failures.
    """
    _logger = logging.getLogger(f"{__name__}.{batch_id}")

    @make_retry(
        max_attempts=max_network_retries,
        backoff=backoff_base,
        retry_on=_NETWORK_ERRORS,
        logger=_logger,
        label=f"batch {batch_id}",
    )
    def _execute(p, bid):
        try:
            return complete(
                p,
                model=model,
                temperature=temperature,
                response_format=response_format,
            )
        except RateLimitError:
            _logger.warning(
                "Rate limit 429 for batch %s, sleeping %ds",
                bid,
                rate_limit_sleep_seconds,
            )
            time.sleep(rate_limit_sleep_seconds)
            _logger.warning("Retrying batch %s after rate-limit sleep", bid)
            return complete(
                p,
                model=model,
                temperature=temperature,
                response_format=response_format,
            )
        except BadRequestError as e:
            if "context length" in str(e).lower():
                _logger.warning("Token limit exceeded for batch %s", bid)
                raise TokenLimitError(bid) from e
            raise
        except _NETWORK_ERRORS:
            raise

    return _execute(prompt, batch_id)


def infer_batch_with_retry(
    batch: Batch,
    render_fn: Callable[[Batch], PromptBundle],
    **kwargs,
) -> list:
    """Infer a batch with full retry including batch splitting.

    Calls :func:`call_complete_with_retry`, and on ``TokenLimitError``
    automatically splits the batch in half and retries each half
    recursively.

    Parameters
    ----------
    batch : Batch
        The batch to infer.
    render_fn : Callable[[Batch], PromptBundle]
        Prompt renderer (e.g. ``render_code_prompt``).
    **kwargs
        Forwarded to :func:`call_complete_with_retry`.

    Returns
    -------
    list
        ``ChatCompletion`` objects (one per call; multiple if split).
    """
    prompt = render_fn(batch)
    try:
        return [call_complete_with_retry(prompt, batch.batch_id, **kwargs)]
    except TokenLimitError:
        logger.warning("Splitting batch %s due to token limit", batch.batch_id)
        results: list = []
        for half in split_batch_in_half(batch):
            results.extend(infer_batch_with_retry(half, render_fn, **kwargs))
        return results
