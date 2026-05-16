"""Batch LLM inference service to group approved codes into themes.

For each tag with approved codes, batches <=5 codes to LLM with theme
prompt.  Returns ThemeInference objects.  Updates inference_status for
each code (entity_type=code, stage=theme, status=generated).

Usage:
    from inference.theme_inference import infer_themes

    themes = infer_themes(con, tag="Problem.Cause")
    # -> list[ThemeInference]
"""

from __future__ import annotations

import time
from functools import partial
from typing import Any

import duckdb
from config import (
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
    theme_model,
    theme_temperature,
)
from utils.logging import get_logger

from .batch_processor import record_tokens, run_batches
from .batching import Batch, group_by_tag
from .fewshot_loader import load_fewshot
from .inference_status_types import ENTITY_CODE, STAGE_THEME
from .parsing import ThemeInference, parse_theme_response
from .prompts import PromptBundle, render_theme_prompt
from .retry import infer_batch_with_retry
from .status_updates import mark_failure, mark_success
from .tag_context import get_tag_metadata
from .theme_code_loading import _CodeRow, load_approved_codes_grouped
from .theme_postprocess import (
    auto_merge_single_code_themes,
    dedup_theme_names,
    flag_small_themes,
    validate_code_belonging,
)
from .tracking import format_stage_summary

logger = get_logger(__name__)

__all__ = ["infer_themes"]


def _codes_to_dicts(items: list[_CodeRow]) -> list[dict[str, Any]]:
    """Convert ``_CodeRow`` items to dicts for Jinja2 template context."""
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "definition": item.definition,
            "exemplar_count": item.exemplar_count,
            "exemplar_contents": list(item.exemplar_contents),
        }
        for item in items
    ]


def _render_theme_prompt_for_batch(
    batch: Batch,
    fewshot: list[dict] | None,
    tag_name: str,
    tag_description: str,
    ontology_path: list[str],
) -> PromptBundle:
    """Render theme inference prompt for a single batch of codes."""
    return render_theme_prompt(
        fewshot=fewshot,
        tag_name=tag_name,
        tag_description=tag_description,
        ontology_path=ontology_path,
        codes=_codes_to_dicts(batch.items),
    )


def _process_theme_batch(
    con: duckdb.DuckDBPyConnection,
    batch: Batch,
    tracker,
) -> list[ThemeInference]:
    """Process a single batch of codes: render, infer, parse, validate."""
    tag_name = batch.tag
    tag_description, ontology_path = get_tag_metadata(tag_name)

    fewshot = (
        load_fewshot(
            "theme_inference", count=fewshot_count(), shuffle=fewshot_shuffle()
        )
        if fewshot_enabled()
        else None
    )

    responses = infer_batch_with_retry(
        batch=batch,
        render_fn=partial(
            _render_theme_prompt_for_batch,
            fewshot=fewshot,
            tag_name=tag_name,
            tag_description=tag_description,
            ontology_path=ontology_path,
        ),
        temperature=theme_temperature(),
        model=theme_model(),
        response_format={"type": "json_object"},
    )

    for resp in responses:
        record_tokens(resp, tracker, STAGE_THEME, batch.batch_id)

    themes: list[ThemeInference] = []
    for resp in responses:
        themes.extend(parse_theme_response(resp.choices[0].message.content))

    themes = dedup_theme_names(themes)
    themes = flag_small_themes(themes)
    themes = auto_merge_single_code_themes(themes, con)

    batch_code_ids = {str(item.id) for item in batch.items}
    validate_code_belonging(themes, batch_code_ids, batch.batch_id)

    covered_code_ids: set[str] = set()
    for theme in themes:
        for cid in theme.code_ids:
            covered_code_ids.add(cid)

    for item in batch.items:
        sid = str(item.id)
        if sid in covered_code_ids:
            mark_success(con, item.id, ENTITY_CODE, STAGE_THEME)
        else:
            mark_failure(con, item.id, "Code not assigned to any theme by LLM")

    return themes


def _log_theme_summary(
    start_time: float,
    results: list,
    tracker,
) -> None:
    """Log completion message with count, elapsed time, and token summary."""
    elapsed = time.time() - start_time
    logger.info(
        "Theme inference complete: %d themes in %.1fs. %s",
        len(results),
        elapsed,
        format_stage_summary(STAGE_THEME, tracker.stage_summary(STAGE_THEME)),
    )


def infer_themes(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
) -> list[ThemeInference]:
    """Batch LLM inference to group approved codes into themes.

    For each tag (or a single *tag*), loads approved code nodes from
    the graph, groups them into batches of <=5, calls Groq with the
    theme inference prompt, parses ``ThemeInference`` responses, and
    returns the aggregated list.

    Args:
        con: Active DuckDB connection.
        tag: Optional ontology tag.  ``None`` discovers all tags with
            approved codes.

    Returns:
        Flat list of ``ThemeInference`` items across all processed tags.

    Logs per-tag summary: ``"Tag 'Problem.Cause': 12 codes -> 3 themes"``.
    """
    start_time = time.time()
    logger.info(
        "Starting theme inference%s",
        f" for tag '{tag}'" if tag else "",
    )

    codes_by_tag = load_approved_codes_grouped(con, tag=tag)
    if not codes_by_tag:
        logger.info("No approved codes found for theme inference")
        return []

    def failure_fn(c, item, err):
        mark_failure(c, item.id, err)

    all_themes: list[ThemeInference] = []
    for tagname, codes in codes_by_tag.items():
        batches = group_by_tag(codes, max_per_batch=5, prefix="theme")
        logger.info(
            "Tag '%s': %d codes -> %d batch(es)",
            tagname,
            len(codes),
            len(batches),
        )
        tag_themes, tracker = run_batches(
            con, batches, _process_theme_batch, STAGE_THEME, failure_fn
        )
        logger.info(
            "Tag '%s': %d codes -> %d themes",
            tagname,
            len(codes),
            len(tag_themes),
        )
        all_themes.extend(tag_themes)

    _log_theme_summary(start_time, all_themes, tracker)
    return all_themes
