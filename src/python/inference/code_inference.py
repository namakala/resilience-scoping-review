"""Batch LLM inference service to generate codes from exemplars.

Groups pending exemplars by tag into batches, renders prompts with ontology
context and existing codes, calls Groq with retry logic, parses structured
responses, updates inference status, and returns CodeInference objects.

Usage:
    from inference.code_inference import infer_codes

    with duckdb.connect(...) as con:
        codes = infer_codes(con, tag=None)
        for c in codes:
            print(c.code_name, c.definition)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial
from typing import Any

import duckdb
import polars as pl
from config import code_temperature, fewshot_count, fewshot_enabled, fewshot_shuffle
from graph import get_nodes_by_type_and_tag
from persistence.loaders import load_exemplars
from utils.logging import get_logger

from .batch_processor import record_tokens, run_batches
from .batching import Batch, group_by_tag
from .fewshot_loader import load_fewshot
from .inference_status_queries import get_pending_items
from .inference_status_types import STAGE_CODE
from .parsing import CodeInference, parse_code_response
from .prompts import PromptBundle, render_code_prompt
from .retry import infer_batch_with_retry
from .status_updates import mark_failure, mark_success
from .tag_context import get_tag_metadata
from .tracking import format_stage_summary

logger = get_logger(__name__)

__all__ = ["infer_codes"]


@dataclass(frozen=True)
class _ExemplarRow:
    """Minimal exemplar data needed for code inference."""

    id: int
    content: str
    keywords: list[str]


def _load_pending_exemplars(
    con: duckdb.DuckDBPyConnection, tag: str | None = None
) -> list[_ExemplarRow]:
    """Load pending exemplars for code inference stage."""
    pending_ids = get_pending_items(con, stage=STAGE_CODE, tag=tag)
    if not pending_ids:
        return []

    try:
        exemplar_ids = [int(x) for x in pending_ids]
    except ValueError as e:
        logger.error("Invalid exemplar_id in inference_status: %s", e)
        raise

    lf = load_exemplars().select(["id", "content", "keywords"])
    lf = lf.filter(pl.col("id").is_in(exemplar_ids)).sort("id")

    rows = []
    for row in lf.collect().iter_rows(named=True):
        rows.append(
            _ExemplarRow(
                id=row["id"],
                content=row["content"],
                keywords=row["keywords"] or [],
            )
        )
    logger.info(
        "Loaded %d pending exemplars%s",
        len(rows),
        f" for tag '{tag}'" if tag else "",
    )
    return rows


def _get_existing_codes_for_tag(tag: str) -> list[dict[str, str]]:
    """Fetch approved codes for a tag to provide context in the prompt."""
    nodes = get_nodes_by_type_and_tag("code", tag)
    approved = [n for n in nodes if n.get("status") == "approved"]
    result = [
        {"name": n["name"], "definition": n["definition"]}
        for n in sorted(approved, key=lambda n: n["id"])
    ]
    logger.debug("Found %d approved codes for tag '%s'", len(result), tag)
    return result


def _prepare_exemplars_dict(
    items: list[_ExemplarRow],
) -> list[dict[str, Any]]:
    """Convert batch items to list of exemplar dicts for prompt context."""
    return [
        {"id": item.id, "content": item.content, "keywords": item.keywords}
        for item in items
    ]


def _render_code_prompt_for_batch(
    batch: Batch,
    fewshot: list[dict] | None,
    ontology_path: list[str],
    tag_description: str,
    existing_codes: list[dict[str, str]],
) -> PromptBundle:
    """Render code inference prompt for a (possibly split) batch."""
    return render_code_prompt(
        fewshot=fewshot,
        ontology_path=ontology_path,
        tag_description=tag_description,
        existing_codes=existing_codes,
        exemplars=_prepare_exemplars_dict(batch.items),
    )


def _process_code_batch(
    con: duckdb.DuckDBPyConnection,
    batch: Batch,
    tracker,
) -> list[CodeInference]:
    """Run code inference for a single batch: fetch context, call LLM, parse, validate.

    Returns the list of successfully generated :class:`CodeInference` objects
    for this batch. Side effects: updates inference_status via mark_success/mark_failure
    and records token usage via the tracker.
    """
    tag_description, ontology_path = get_tag_metadata(batch.tag)
    existing_codes = _get_existing_codes_for_tag(batch.tag)

    fewshot = None
    if fewshot_enabled():
        fewshot = load_fewshot(
            "code_inference",
            count=fewshot_count(),
            shuffle=fewshot_shuffle(),
        )

    responses = infer_batch_with_retry(
        batch=batch,
        render_fn=partial(
            _render_code_prompt_for_batch,
            fewshot=fewshot,
            ontology_path=ontology_path,
            tag_description=tag_description,
            existing_codes=existing_codes,
        ),
        temperature=code_temperature(),
        response_format={"type": "json_object"},
    )

    all_parsed: list[CodeInference] = []
    for resp in responses:
        all_parsed.extend(parse_code_response(resp.choices[0].message.content))
        record_tokens(resp, tracker, STAGE_CODE, batch.batch_id)

    # dedup by exemplar_id (keep first)
    code_map: dict[str, CodeInference] = {}
    for c in all_parsed:
        if c.exemplar_id not in code_map:
            code_map[c.exemplar_id] = c
        else:
            logger.debug(
                "Duplicate code for exemplar %s across batch splits; keeping first",
                c.exemplar_id,
            )

    # validate
    batch_ids = {str(it.id) for it in batch.items}
    parsed_ids = set(code_map.keys())
    missing = batch_ids - parsed_ids
    if missing:
        logger.error(
            "Batch %s: %d exemplars missing codes: %s",
            batch.batch_id,
            len(missing),
            sorted(missing),
        )
    extra = parsed_ids - batch_ids
    if extra:
        logger.warning(
            "Batch %s: %d codes for unknown exemplars: %s",
            batch.batch_id,
            len(extra),
            sorted(extra),
        )

    # update status and collect results
    results: list[CodeInference] = []
    for item in batch.items:
        eid_str = str(item.id)
        if eid_str in code_map:
            mark_success(con, item.id, "exemplar", "code")
            results.append(code_map[eid_str])
        else:
            mark_failure(con, item.id, "No code generated by LLM")
    return results


def infer_codes(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
) -> list[CodeInference]:
    """Run batch code inference for all pending exemplars.

    For each tag with pending exemplars:
      1. Fetch pending exemplars grouped by tag (≤15 per batch).
      2. For each batch: fetch context, call LLM, parse, validate, update status.
      3. Collect all CodeInference objects.

    Args:
        con: Active DuckDB connection.
        tag: Optional tag filter; if None, process all pending exemplars.

    Returns:
        List of CodeInference objects (all successfully generated codes).
    """
    start_time = time.time()
    logger.info(
        "Starting code inference%s",
        f" for tag '{tag}'" if tag else "",
    )

    exemplars = _load_pending_exemplars(con, tag=tag)
    if not exemplars:
        logger.info("No pending exemplars for code inference")
        return []

    batches = group_by_tag(exemplars, max_per_batch=15, prefix="code")
    logger.info("Prepared %d batches for code inference", len(batches))

    def failure_fn(c, item, err):
        mark_failure(c, item.id, err)

    results, tracker = run_batches(
        con,
        batches,
        _process_code_batch,
        STAGE_CODE,
        failure_fn,
    )

    elapsed = time.time() - start_time
    rate = len(results) / elapsed if elapsed > 0 else 0
    summary = tracker.stage_summary(STAGE_CODE)
    logger.info(
        "Code inference complete: %d codes in %.1fs (%.1f codes/sec). %s",
        len(results),
        elapsed,
        rate,
        format_stage_summary(STAGE_CODE, summary),
    )

    return results
