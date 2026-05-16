"""Groq async + sync client singleton for LLM inference.

Provides low-level client access (get_client, get_sync_client) and a
high-level :func:`complete` that builds a properly role-structured
messages array from a :class:`PromptBundle`.

Usage:
    from inference.groq_client import (
        get_client, get_sync_client, get_model,
        build_messages, complete,
    )
    from inference.prompts import render_code_prompt

    bundle = render_code_prompt(...)
    reply = complete(bundle)
    print(reply.choices[0].message.content)
"""

import re
import time
from dataclasses import dataclass

from config import default_model, groq_api_key, groq_max_retries, groq_timeout
from groq import AsyncGroq, Groq

from .llm_logger import log_llm_call
from .prompts import PromptBundle

__all__ = [
    "get_client",
    "get_sync_client",
    "get_model",
    "get_rate_limit_state",
    "set_client",
    "reset_client",
    "build_messages",
    "complete",
]

_client: AsyncGroq | None = None
_sync_client: Groq | None = None


@dataclass
class _RateLimitState:
    """Tracks ``x-ratelimit-*`` headers from the last Groq response.

    Used by :func:`_proactive_rate_limit_check` in the retry layer to
    avoid hitting 429 errors preemptively."""

    remaining_tokens: int = -1
    """``x-ratelimit-remaining-tokens`` — Tokens Per Minute remaining."""
    remaining_requests: int = -1
    """``x-ratelimit-remaining-requests`` — Requests Per Day remaining."""
    reset_tokens_seconds: float = 0.0
    """``x-ratelimit-reset-tokens`` — Seconds until TPM resets."""
    reset_requests_seconds: float = 0.0
    """``x-ratelimit-reset-requests`` — Seconds until RPD resets."""
    last_updated: float = 0.0
    """``time.time()`` when the state was last updated."""


_rate_limit_state = _RateLimitState()


def _parse_duration(duration: str) -> float:
    """Parse a Groq ``x-ratelimit-reset-*`` duration like ``2m59.56s`` or ``7.66s``.

    Returns total seconds as a float. Returns 0.0 if the string cannot
    be parsed.
    """
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", duration.strip())
    if not match:
        return 0.0
    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _update_from_headers(headers) -> None:
    """Extract ``x-ratelimit-*`` headers into the module-level state singleton."""
    state = _rate_limit_state
    remaining_tokens = headers.get("x-ratelimit-remaining-tokens")
    remaining_requests = headers.get("x-ratelimit-remaining-requests")
    reset_tokens = headers.get("x-ratelimit-reset-tokens")
    reset_requests = headers.get("x-ratelimit-reset-requests")

    if remaining_tokens is not None:
        state.remaining_tokens = int(remaining_tokens)
    if remaining_requests is not None:
        state.remaining_requests = int(remaining_requests)
    if reset_tokens is not None:
        state.reset_tokens_seconds = _parse_duration(reset_tokens)
    if reset_requests is not None:
        state.reset_requests_seconds = _parse_duration(reset_requests)
    state.last_updated = time.time()


def get_rate_limit_state() -> _RateLimitState:
    """Return the current rate limit state from the last response.

    Fields are -1 / 0.0 before the first API call returns.
    """
    return _rate_limit_state


def get_client() -> AsyncGroq:
    """Return the singleton AsyncGroq client, creating it if needed."""
    global _client
    if _client is None:
        _client = AsyncGroq(
            api_key=groq_api_key(),
            timeout=groq_timeout(),
            max_retries=groq_max_retries(),
        )
    return _client


def get_sync_client() -> Groq:
    """Return the singleton Groq (sync) client, creating it if needed."""
    global _sync_client
    if _sync_client is None:
        _sync_client = Groq(
            api_key=groq_api_key(),
            timeout=groq_timeout(),
            max_retries=groq_max_retries(),
        )
    return _sync_client


def get_model() -> str:
    """Return the configured LLM model name."""
    return default_model()


def set_client(client: AsyncGroq) -> None:
    """Override the async client singleton (for testing / DI)."""
    global _client
    _client = client


def reset_client() -> None:
    """Reset all client singletons (for test isolation)."""
    global _client, _sync_client
    _client = None
    _sync_client = None


def build_messages(
    system: str,
    user: str,
    fewshot: list[dict] | None = None,
) -> list[dict]:
    """Build a messages array with proper Groq-supported roles.

    Produces::

        [{"role": "system", "content": <system>},
         {"role": "user", "content": <fewshot[0].user>},
         {"role": "assistant", "content": <fewshot[0].assistant>},
         ...,
         {"role": "user", "content": <user>}]

    Parameters
    ----------
    system : str
        System prompt (role, schema, rules).
    user : str
        User prompt (batch-specific data).
    fewshot : list[dict] | None
        Optional few-shot demonstrations; each dict must have
        ``"user"`` and ``"assistant"`` keys.

    Returns
    -------
    list[dict]
        Messages array ready for ``client.chat.completions.create``.
    """
    messages: list[dict] = [{"role": "system", "content": system}]
    if fewshot:
        for ex in fewshot:
            messages.append({"role": "user", "content": ex["user"]})
            messages.append({"role": "assistant", "content": ex["assistant"]})
    messages.append({"role": "user", "content": user})
    return messages


def complete(
    prompt: PromptBundle,
    model: str | None = None,
    temperature: float = 0.0,
    response_format: dict | None = None,
    batch_id: str = "",
    tag: str = "",
):
    """Send a :class:`PromptBundle` to Groq and return the completion.

    Assembles a role-structured messages array, sets JSON output mode
    and zero temperature by default.

    Parameters
    ----------
    prompt : PromptBundle
        Split system/user/fewshot prompt content.
    model : str | None
        Model override; uses ``get_model()`` if not given.
    temperature : float
        Sampling temperature (default ``0.0`` for deterministic).
    response_format : dict | None
        Groq ``response_format`` parameter; defaults to
        ``{"type": "json_object"}``.
    batch_id : str
        Batch identifier for logging (default ``""``).
    tag : str
        Ontology tag for logging (default ``""``).

    Returns
    -------
    ChatCompletion
        The full Groq completion object. Access the text via
        ``.choices[0].message.content``.
    """
    messages = build_messages(prompt.system, prompt.user, prompt.fewshot)
    client = get_sync_client()
    model = model or get_model()
    raw_response = client.chat.completions.with_raw_response.create(
        messages=messages,
        model=model,
        temperature=temperature,
        response_format=response_format or {"type": "json_object"},
    )
    _update_from_headers(raw_response.headers)
    reply = raw_response.parse()
    log_llm_call(
        batch_id=batch_id,
        tag=tag,
        model=model,
        temperature=temperature,
        prompt_system=prompt.system,
        prompt_user=prompt.user,
        response=reply.choices[0].message.content,
        token_usage=(
            {
                "input_tokens": getattr(reply.usage, "prompt_tokens", 0),
                "output_tokens": getattr(reply.usage, "completion_tokens", 0),
            }
            if reply.usage
            else {}
        ),
    )
    return reply
