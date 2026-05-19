"""Ephemeral LLM prompt/response logger — each call appended immediately.

Usage:
    from inference.llm_logger import set_llm_log_path, log_llm_call, flush_llm_log

    set_llm_log_path("data/output/llm_output.json")

    log_llm_call(
        batch_id="code_T1_batch_00",
        tag="Problem.Cause",
        model="llama-70b",
        prompt_system="...",
        prompt_user="...",
        response="...",
    )
    flush_llm_log()  # optional final rewrite as clean JSON array
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_entries: list[dict[str, Any]] = []
_output_path: Path | None = None


def set_llm_log_path(path: str | Path) -> None:
    """Set the output file path for per-call logging.

    Must be called before any ``log_llm_call`` invocation.
    """
    global _output_path  # noqa: PLW0603
    _output_path = Path(path)
    _output_path.parent.mkdir(parents=True, exist_ok=True)


def _write_one(entry: dict[str, Any]) -> None:
    """Append *entry* as a single JSON line to the output file."""
    if _output_path is None:
        return
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(str(_output_path), "a", encoding="utf-8") as f:
        f.write(line)


def log_llm_call(
    batch_id: str,
    tag: str,
    model: str,
    prompt_system: str,
    prompt_user: str,
    response: str,
    temperature: float = 0.0,
    token_usage: dict[str, int] | None = None,
) -> None:
    """Record one LLM call — buffered *and* immediately persisted."""
    entry = {
        "batch_id": batch_id,
        "tag": tag,
        "model": model,
        "temperature": temperature,
        "prompt_system": prompt_system,
        "prompt_user": prompt_user,
        "response": response,
        "token_usage": token_usage or {},
    }
    _entries.append(entry)
    _write_one(entry)


def flush_llm_log() -> None:
    """Rewrite the output file as a clean JSON array from the buffer.

    Overwrites the per-call JSON Lines file with a proper JSON array
    so that downstream consumers always see a valid ``[...]`` document.
    Call once at the end of a pipeline run.
    """
    if not _entries or _output_path is None:
        return
    _output_path.write_text(
        json.dumps(_entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
