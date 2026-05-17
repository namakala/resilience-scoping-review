"""Batch LLM inference service to synthesize cross-cutting interpretations.

For each contiguous tag span (≥2 ready tags), loads approved themes,
builds prompt context (tag hierarchy, ontology subtree, themes grouped
by tag), calls Groq with interpretation prompt, parses
``InterpretationInference`` responses, and post-processes results.

Usage:
    from inference.interpretation_synthesis import synthesize_interpretations

    interps = synthesize_interpretations(con)
    # -> list[InterpretationInference]
"""

from __future__ import annotations

import time
from collections.abc import Callable

import duckdb
from utils.logging import get_logger

from .batch_processor import run_batches
from .inference_status_types import STAGE_INTERPRETATION
from .interpretation_batch_builder import build_interpretation_batches
from .interpretation_span_grouping import group_ready_tags_into_spans
from .interpretation_span_processor import _process_interpretation_span
from .parsing import InterpretationInference
from .readiness import get_ready_tags
from .status_updates import mark_failure
from .tracking import format_stage_summary

logger = get_logger(__name__)

__all__ = ["synthesize_interpretations"]


def _mark_span_failure(c, item, err):
    """Failure handler for span batches — marks all themes as failed."""
    for tag_themes in item.themes_by_tag.values():
        for theme in tag_themes:
            mark_failure(c, theme.id, err)


def _log_summary(
    start_time: float,
    results: list[InterpretationInference],
    tracker,
) -> None:
    elapsed = time.time() - start_time
    logger.info(
        "Interpretation synthesis complete: %d interpretations in %.1fs. %s",
        len(results),
        elapsed,
        format_stage_summary(
            STAGE_INTERPRETATION, tracker.stage_summary(STAGE_INTERPRETATION)
        ),
    )


def synthesize_interpretations(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
    tags: list[str] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[InterpretationInference]:
    """Synthesize cross-cutting interpretations from approved themes.

    Discovers ready tags from ``session_state['interpretation_ready_tags']``,
    groups them into contiguous subtrees, and processes each span with ≥2
    tags via LLM batch inference.

    Args:
        con: Active DuckDB connection.
        tag: Optional tag override. If provided, only this tag is checked
            for readiness (instead of auto-discovering all ready tags).
        tags: Optional list of tags. If provided, ready tags are filtered
            to only those in this list.  Mutually exclusive with *tag*.

    Returns:
        Flat list of ``InterpretationInference`` items across all spans.
    """
    if tag is not None and tags is not None:
        raise ValueError("Provide either 'tag' or 'tags', not both")

    start_time = time.time()
    logger.info(
        "Starting interpretation synthesis%s",
        f" for tag '{tag}'" if tag else f" for {len(tags)} tag(s)" if tags else "",
    )

    ready_tags = get_ready_tags(con)
    if tag:
        ready_tags = [t for t in ready_tags if t == tag]
    if tags:
        from ontology import get_ancestors

        _expanded = set(tags)
        for t in tags:
            _expanded.update(get_ancestors(t))
        ready_tags = [t for t in ready_tags if t in _expanded]
    if not ready_tags:
        logger.info("No ready tags found for interpretation synthesis")
        return []

    spans = [s for s in group_ready_tags_into_spans(set(ready_tags)) if len(s) >= 2]
    if not spans:
        logger.info("No multi-tag spans found among ready tags")
        return []

    batches = build_interpretation_batches(spans)
    if not batches:
        logger.info("No spans with approved themes to process")
        return []

    all_results, tracker = run_batches(
        con,
        batches,
        _process_interpretation_span,
        STAGE_INTERPRETATION,
        _mark_span_failure,
        progress_callback=progress_callback,
    )

    _log_summary(start_time, all_results, tracker)
    return all_results
