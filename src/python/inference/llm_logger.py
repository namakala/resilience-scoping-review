"""Ephemeral LLM prompt/response logger — replaced every run.

Usage:
    from inference.llm_logger import log_llm_call, flush_llm_log

    log_llm_call(
        batch_id="code_T1_batch_00",
        tag="Problem.Cause",
        model="llama-70b",
        prompt_system="...",
        prompt_user="...",
        response="...",
    )
    flush_llm_log("data/output/llm_output.json")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_entries: list[dict[str, Any]] = []


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
    """Record one LLM call for the ephemeral log."""
    _entries.append(
        {
            "batch_id": batch_id,
            "tag": tag,
            "model": model,
            "temperature": temperature,
            "prompt_system": prompt_system,
            "prompt_user": prompt_user,
            "response": response,
            "token_usage": token_usage or {},
        }
    )


def flush_llm_log(output_path: str | Path) -> None:
    """Write all accumulated entries as a JSON array and clear the buffer.

    Replaces any existing file at *output_path* (ephemeral — overwritten
    every run).
    """
    if not _entries:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _entries.clear()
