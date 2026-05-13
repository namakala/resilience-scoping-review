"""Groq async + sync client singleton for LLM inference.

Usage:
    from inference.groq_client import get_client, get_sync_client, get_model

    client = get_client()
    model = get_model()
    response = await client.chat.completions.create(
        messages=[{"role": "user", "content": "Hello"}],
        model=model,
        max_tokens=5,
    )
"""

from config import groq_api_key, groq_max_retries, groq_model, groq_timeout
from groq import AsyncGroq, Groq

__all__ = [
    "get_client",
    "get_sync_client",
    "get_model",
    "set_client",
    "reset_client",
]

_client: AsyncGroq | None = None
_sync_client: Groq | None = None


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
    return groq_model()


def set_client(client: AsyncGroq) -> None:
    """Override the async client singleton (for testing / DI)."""
    global _client
    _client = client


def reset_client() -> None:
    """Reset all client singletons (for test isolation)."""
    global _client, _sync_client
    _client = None
    _sync_client = None
