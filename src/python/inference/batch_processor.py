"""Shared batch loop, error handling, and token recording for inference services.

Provides :func:`run_batches` and :func:`record_tokens` to reduce
boilerplate across code inference, theme inference, and interpretation
synthesis services.

Usage:
    from inference.batch_processor import run_batches, record_tokens

    all_results, tracker = run_batches(
        con, batches, process_fn, stage, failure_fn,
    )
"""

from __future__ import annotations

import time
from typing import Any, Callable

from utils.logging import get_logger

from .batching import Batch
from .tracking import TokenTracker, get_tracker

logger = get_logger(__name__)


def run_batches(
    con: Any,
    batches: list[Batch],
    process_fn: Callable[[Any, Batch, TokenTracker], list],
    stage: str,
    failure_fn: Callable[[Any, Any, str], None],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[list, TokenTracker]:
    """Run *process_fn* for each batch with error handling and timing.

    *process_fn* receives ``(con, batch, tracker)`` and must return the
    list of successfully generated artifacts for that batch. If it
    raises any exception, *failure_fn* is called for every item in the
    batch and processing continues with the next batch.

    Args:
        con: DuckDB connection (forwarded to *process_fn* and *failure_fn*).
        batches: List of :class:`Batch` objects to process sequentially.
        process_fn: Per-batch callback. ``(con, Batch, TokenTracker) -> list``.
        stage: Pipeline stage constant for token tracking.
        failure_fn: Called per item on unhandled batch exceptions.
                     Signature: ``(con, item, error_message)``.
        progress_callback: Optional callback ``(total, completed, desc)``
            for TUI progress reporting.

    Returns:
        ``(all_results, tracker)`` where *tracker* is the singleton
        :class:`TokenTracker` with all recorded usage from the run.
    """
    tracker = get_tracker()
    all_results: list = []
    total_batches = len(batches)
    for batch_idx, batch in enumerate(batches, start=1):
        batch_start = time.time()
        logger.info("Processing batch %s (%d items)", batch.batch_id, batch.item_count)
        try:
            results = process_fn(con, batch, tracker)
            all_results.extend(results)
            logger.info(
                "Batch %s complete: %d results, %.1fs",
                batch.batch_id,
                len(results),
                time.time() - batch_start,
            )
        except Exception:
            logger.exception(
                "Batch %s failed; marking all items as failed", batch.batch_id
            )
            for item in batch.items:
                failure_fn(con, item, "Batch processing error")
        if progress_callback:
            progress_callback(
                total_batches,
                batch_idx,
                f"{stage}: batch {batch.batch_id}",
            )
    return all_results, tracker


def record_tokens(
    resp: Any,
    tracker: TokenTracker,
    stage: str,
    batch_id: str,
) -> None:
    """Extract token usage from a Groq response and record it.

    Safe to call with responses that have no ``usage`` attribute
    (e.g. mock responses in tests).

    Args:
        resp: Groq ``ChatCompletion`` response (or mock with ``.usage``).
        tracker: Active :class:`TokenTracker` instance.
        stage: Pipeline stage constant.
        batch_id: Batch identifier for the log record.
    """
    usage = getattr(resp, "usage", None)
    if usage:
        tracker.record(
            stage=stage,
            batch_id=batch_id,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )
