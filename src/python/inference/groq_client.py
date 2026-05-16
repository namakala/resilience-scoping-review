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

from config import groq_api_key, groq_max_retries, groq_model, groq_timeout
from groq import AsyncGroq, Groq

from .llm_logger import log_llm_call
from .prompts import PromptBundle

__all__ = [
    "get_client",
    "get_sync_client",
    "get_model",
    "set_client",
    "reset_client",
    "build_messages",
    "complete",
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
    reply = client.chat.completions.create(
        messages=messages,
        model=model,
        temperature=temperature,
        response_format=response_format or {"type": "json_object"},
    )
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
