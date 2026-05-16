"""Batch LLM inference service to generate codes from exemplars.

Groups pending exemplars by tag into batches, renders prompts with ontology
context and existing codes, calls Groq with retry logic, parses structured
responses, updates inference status, and returns CodeInference objects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial
from typing import Any

import duckdb
import polars as pl
from config import (
    code_model,
    code_temperature,
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
)
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
    id: int
    content: str
    keywords: list[str]
    tag: str


def _load_pending_exemplars(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
    tags: list[str] | None = None,
) -> list[_ExemplarRow]:
    if tag is not None and tags is not None:
        raise ValueError("Provide either 'tag' or 'tags', not both")

    pending_ids = get_pending_items(con, stage=STAGE_CODE, tag=tag, tags=tags)
    if not pending_ids:
        return []

    try:
        exemplar_ids = [int(x) for x in pending_ids]
    except ValueError as e:
        logger.error("Invalid exemplar_id in inference_status: %s", e)
        raise

    rows = []
    for row in (
        load_exemplars()
        .select(["id", "content", "keywords", "tag"])
        .filter(pl.col("id").is_in(exemplar_ids))
        .sort("id")
        .collect()
        .iter_rows(named=True)
    ):
        rows.append(
            _ExemplarRow(
                id=row["id"],
                content=row["content"],
                keywords=row["keywords"] or [],
                tag=row["tag"],
            )
        )
    logger.info(
        "Loaded %d pending exemplars%s",
        len(rows),
        f" for tag '{tag}'" if tag else "",
    )
    return rows


def _get_existing_codes_for_tag(tag: str) -> list[dict[str, str]]:
    nodes = get_nodes_by_type_and_tag("code", tag)
    approved = [
        {"name": n["name"], "definition": n["definition"]}
        for n in sorted(
            (n for n in nodes if n.get("status") == "approved"), key=lambda n: n["id"]
        )
    ]
    logger.debug("Found %d approved codes for tag '%s'", len(approved), tag)
    return approved


def _exemplars_to_dicts(items: list[_ExemplarRow]) -> list[dict[str, Any]]:
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
    return render_code_prompt(
        fewshot=fewshot,
        ontology_path=ontology_path,
        tag_description=tag_description,
        existing_codes=existing_codes,
        exemplars=_exemplars_to_dicts(batch.items),
    )


def _dedup_and_validate(responses, batch: Batch) -> dict[str, CodeInference]:
    """Parse LLM responses into CodeInference map; dedup by exemplar_id."""
    parsed: list[CodeInference] = []
    for resp in responses:
        parsed.extend(parse_code_response(resp.choices[0].message.content))

    code_map: dict[str, CodeInference] = {}
    for c in parsed:
        if c.exemplar_id not in code_map:
            code_map[c.exemplar_id] = c

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
    return code_map


def _log_code_summary(start_time: float, results: list, tracker) -> None:
    elapsed = time.time() - start_time
    rate = len(results) / elapsed if elapsed > 0 else 0
    logger.info(
        "Code inference complete: %d codes in %.1fs (%.1f codes/sec). %s",
        len(results),
        elapsed,
        rate,
        format_stage_summary(STAGE_CODE, tracker.stage_summary(STAGE_CODE)),
    )


def _process_code_batch(
    con: duckdb.DuckDBPyConnection,
    batch: Batch,
    tracker,
) -> list[CodeInference]:
    tag_description, ontology_path = get_tag_metadata(batch.tag)
    existing_codes = _get_existing_codes_for_tag(batch.tag)

    fewshot = (
        load_fewshot("code_inference", count=fewshot_count(), shuffle=fewshot_shuffle())
        if fewshot_enabled()
        else None
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
        model=code_model(),
        response_format={"type": "json_object"},
    )

    for resp in responses:
        record_tokens(resp, tracker, STAGE_CODE, batch.batch_id)

    code_map = _dedup_and_validate(responses, batch)

    results: list[CodeInference] = []
    for item in batch.items:
        eid = str(item.id)
        if eid in code_map:
            c = code_map[eid]
            c.tag = batch.tag
            mark_success(con, item.id, "exemplar", "code")
            results.append(c)
        else:
            mark_failure(con, item.id, "No code generated by LLM")
    return results


def infer_codes(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
    tags: list[str] | None = None,
) -> list[CodeInference]:
    if tag is not None and tags is not None:
        raise ValueError("Provide either 'tag' or 'tags', not both")

    start_time = time.time()
    logger.info(
        "Starting code inference%s",
        f" for tag '{tag}'" if tag else f" for {len(tags)} tag(s)" if tags else "",
    )

    exemplars = _load_pending_exemplars(con, tag=tag, tags=tags)
    if not exemplars:
        logger.info("No pending exemplars for code inference")
        return []

    batches = group_by_tag(exemplars, max_per_batch=15, prefix="code")
    logger.info("Prepared %d batches for code inference", len(batches))

    def failure_fn(c, item, err):
        mark_failure(c, item.id, err)

    results, tracker = run_batches(
        con, batches, _process_code_batch, STAGE_CODE, failure_fn
    )
    _log_code_summary(start_time, results, tracker)
    return results
