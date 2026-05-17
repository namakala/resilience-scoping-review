"""Batch LLM inference service to group approved codes into themes.

For each tag with approved codes, batches <=5 codes to LLM with theme
prompt.  Returns ThemeInference objects.  Updates inference_status for
each code (entity_type=code, stage=theme, status=generated).

Auto-assignment guardrail
-------------------------
Before sending codes to the LLM, each pending code is scored against
existing themes (draft + approved) using hybrid similarity:

    0.6 * cosine(code_emb, theme_emb)
  + 0.2 * direct_BM25(code_definition, theme_narrative)
  + 0.2 * indirect_code_agreement

Codes scoring above ``SIMILARITY_SCORE_THRESHOLD`` are automatically
assigned to the best-matching existing theme, skipping LLM inference.

Usage:
    from inference.theme_inference import infer_themes

    themes = infer_themes(con, tag="Problem.Cause")
    # -> list[ThemeInference]
"""

from __future__ import annotations

import json
import time
from functools import partial
from typing import Any, Callable

import duckdb
import numpy as np
from config import (
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
    similarity_score_threshold,
    theme_model,
    theme_temperature,
)
from graph import (
    create_edge,
    get_graph,
    get_node,
    get_nodes_by_type_and_tag,
    graph_transaction,
)
from graph.transactions import get_active_connection
from persistence.duckdb_connection import DEFAULT_DB_PATH
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

from .batch_processor import record_tokens, run_batches
from .batching import Batch, group_by_tag
from .fewshot_loader import load_fewshot
from .inference_status_crud import set_status
from .inference_status_types import ENTITY_CODE, GENERATED, STAGE_THEME
from .parsing import ThemeInference, parse_theme_response
from .prompts import PromptBundle, render_theme_prompt
from .retry import infer_batch_with_retry
from .status_updates import mark_failure, mark_success
from .tag_context import get_tag_metadata
from .theme_code_loading import _CodeRow, load_approved_codes_grouped
from .theme_postprocess import (
    auto_merge_single_code_themes,
    dedup_code_across_themes,
    dedup_theme_names,
    flag_small_themes,
    validate_code_belonging,
)
from .tracking import format_stage_summary

logger = get_logger(__name__)

__all__ = ["infer_themes"]


def _get_all_existing_themes(
    tag: str,
) -> dict[str, Any]:
    """Load themes from the current tag and all other tags.

    Includes themes with ``status IN ('draft', 'approved')``.
    Excludes ``rejected`` and ``merged``.
    """
    all_nodes = get_nodes_by_type_and_tag("theme", None)
    active = [n for n in all_nodes if n.get("status") in ("draft", "approved")]

    def _to_entry(n: dict) -> dict[str, str]:
        return {"name": n["name"], "narrative": n.get("definition", "")}

    same_tag = [
        _to_entry(n)
        for n in sorted(
            (n for n in active if n.get("tag") == tag),
            key=lambda n: n["id"],
        )
    ]

    other_tags: dict[str, list[dict]] = {}
    for n in sorted(active, key=lambda n: n["id"]):
        t = n.get("tag")
        if t and t != tag:
            other_tags.setdefault(t, []).append(_to_entry(n))

    return {"same_tag": same_tag, "other_tags": other_tags}


def _load_embeddings_bulk(
    con: duckdb.DuckDBPyConnection,
    entity_ids: list[int],
    entity_type: str,
) -> tuple[list[int], np.ndarray]:
    """Load cached embeddings for a list of entity IDs.  Shared with code_inference."""
    present: list[int] = []
    embs: list[np.ndarray] = []
    for eid in entity_ids:
        emb = get_embedding(con, str(eid), entity_type)
        if emb is not None:
            present.append(eid)
            embs.append(emb)
    if not embs:
        raise ValueError(
            f"No {entity_type} embeddings found in cache "
            f"(tried {len(entity_ids)} IDs)"
        )
    return present, np.stack(embs, axis=0)


def _get_tokenizer():
    """Build the BM25 tokenizer matching the pipeline's config."""
    from config import bm25_tokenizer_config
    from semantic.tokenizer import _build_tokenizer, _parse_tokenizer_config

    toggles = _parse_tokenizer_config(bm25_tokenizer_config())
    return _build_tokenizer(toggles)


def _auto_assign_codes_to_themes(
    con: duckdb.DuckDBPyConnection,
    tag: str,
    codes: list[_CodeRow],
) -> tuple[list[_CodeRow], list[_CodeRow]]:
    """Auto-assign codes to existing themes based on hybrid similarity.

    Codes whose combined similarity to an existing theme (draft + approved)
    exceeds ``SIMILARITY_SCORE_THRESHOLD`` are assigned inside an atomic
    ``graph_transaction``.

    Returns ``(auto_assigned, remaining)``.
    """
    if not codes:
        return [], []

    threshold = similarity_score_threshold()
    all_nodes = get_nodes_by_type_and_tag("theme", tag)
    candidate_themes = [
        n for n in all_nodes if n.get("status") in ("draft", "approved")
    ]
    if not candidate_themes:
        return [], codes

    theme_ids = [n["id"] for n in candidate_themes]
    theme_texts = [
        f"{n.get('name', '')} {n.get('definition', '')}" for n in candidate_themes
    ]
    code_ids = [c.id for c in codes]
    code_texts = [f"{c.name} {c.definition}" for c in codes]

    # Load embeddings
    try:
        _, cd_embs = _load_embeddings_bulk(con, code_ids, "code")
        _, th_embs = _load_embeddings_bulk(con, theme_ids, "theme")
    except ValueError as exc:
        logger.warning("Embedding loading failed for theme auto-assign: %s", exc)
        return [], codes

    # Cosine similarity
    cosine_sim = cd_embs @ th_embs.T

    # Direct BM25
    tokenizer = _get_tokenizer()
    from rank_bm25 import BM25Okapi

    theme_corpus = [tokenizer(t) for t in theme_texts]
    bm25 = BM25Okapi(theme_corpus)
    direct_bm25 = np.zeros((len(codes), len(theme_ids)), dtype="float32")
    for i in range(len(codes)):
        raw = np.array(bm25.get_scores(tokenizer(code_texts[i])), dtype="float32")
        direct_bm25[i] = raw
    mn = direct_bm25.min(axis=1, keepdims=True)
    mx = direct_bm25.max(axis=1, keepdims=True)
    span = mx - mn
    span[span == 0] = 1.0
    direct_bm25 = (direct_bm25 - mn) / span

    combined = 0.6 * cosine_sim + 0.4 * direct_bm25
    best_combined = combined.max(axis=1)
    best_idx = combined.argmax(axis=1)
    auto_idxs = set(np.where(best_combined >= threshold)[0].tolist())

    if not auto_idxs:
        return [], codes

    auto_assigned: list[_CodeRow] = []
    remaining: list[_CodeRow] = []
    for i, c in enumerate(codes):
        if i in auto_idxs:
            auto_assigned.append(c)
        else:
            remaining.append(c)

    logger.info(
        "Auto-assigned %d / %d codes to existing themes for tag '%s' (threshold=%.2f)",
        len(auto_assigned),
        len(codes),
        tag,
        threshold,
    )

    # Persist inside atomic transaction
    with graph_transaction(db_path=DEFAULT_DB_PATH):
        for i in auto_idxs:
            c = codes[i]
            tid = theme_ids[best_idx[i]]

            existing = get_node(tid)
            old_dj = existing.get("data_json") or {}
            old_code_ids = set(old_dj.get("code_ids", []))
            sid = str(c.id)
            if sid in old_code_ids:
                continue

            new_code_ids = list(old_code_ids | {sid})
            merged_dj = {**old_dj, "code_ids": new_code_ids}

            tx_con = get_active_connection()
            if tx_con is None:
                raise RuntimeError(
                    "Theme auto-assign requires an active graph_transaction"
                )
            tx_con.execute(
                "UPDATE nodes SET data_json = ? WHERE id = ?",
                [json.dumps(merged_dj, ensure_ascii=False), tid],
            )

            G = get_graph(DEFAULT_DB_PATH)
            attrs = dict(G.nodes[tid])
            attrs["data_json"] = merged_dj
            G.add_node(tid, **attrs)

            create_edge(
                source_id=tid,
                target_id=c.id,
                edge_type="composed-of",
                db_path=DEFAULT_DB_PATH,
            )

            set_status(
                tx_con,
                entity_id=sid,
                entity_type=ENTITY_CODE,
                stage=STAGE_THEME,
                status=GENERATED,
            )

    return auto_assigned, remaining


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
    other_tag_themes: dict[str, list[dict[str, str]]] | None = None,
) -> PromptBundle:
    """Render theme inference prompt for a single batch of codes."""
    return render_theme_prompt(
        fewshot=fewshot,
        tag_name=tag_name,
        tag_description=tag_description,
        ontology_path=ontology_path,
        codes=_codes_to_dicts(batch.items),
        other_tag_themes=other_tag_themes or {},
    )


def _process_theme_batch(
    con: duckdb.DuckDBPyConnection,
    batch: Batch,
    tracker,
) -> list[ThemeInference]:
    """Process a single batch of codes: render, infer, parse, validate."""
    tag_name = batch.tag
    tag_description, ontology_path = get_tag_metadata(tag_name)
    theme_info = _get_all_existing_themes(tag_name)
    other_tag_themes = theme_info["other_tags"]

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
            other_tag_themes=other_tag_themes,
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
    themes = dedup_code_across_themes(themes)

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
    code_ids: list[int] | None = None,
    skip_auto_assign: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[ThemeInference]:
    """Batch LLM inference to group approved codes into themes.

    For each tag (or a single *tag*), loads approved code nodes from
    the graph, auto-assigns high-similarity codes to existing themes,
    then groups remaining codes into batches of <=5 and calls Groq
    with the theme inference prompt.

    When *code_ids* is provided (and *tag* is also given), only those
    specific codes are processed.  This scoped mode is used by split
    re-inference to avoid re-processing the entire tag.

    When *skip_auto_assign* is ``True``, the auto-assignment guardrail
    is bypassed and all codes go directly to the LLM.  Used by split
    re-inference to prevent regrouping from being overridden.

    Args:
        con: Active DuckDB connection.
        tag: Optional ontology tag.  ``None`` discovers all tags with
            approved codes.
        code_ids: Optional list of code IDs to scope processing to.
            Requires *tag* to also be provided.
        skip_auto_assign: If ``True``, skip auto-assignment to existing
            themes and send all codes to LLM directly.

    Returns:
        Flat list of ``ThemeInference`` items across all processed tags.
    """
    if code_ids is not None and tag is None:
        raise ValueError("'code_ids' requires 'tag' to also be provided")

    start_time = time.time()
    logger.info(
        "Starting theme inference%s%s%s",
        f" for tag '{tag}'" if tag else "",
        f" ({len(code_ids)} scoped codes)" if code_ids else "",
        " (skip_auto_assign)" if skip_auto_assign else "",
    )

    codes_by_tag = load_approved_codes_grouped(con, tag=tag, code_ids=code_ids)
    if not codes_by_tag:
        logger.info("No approved codes found for theme inference")
        return []

    def failure_fn(c, item, err):
        mark_failure(c, item.id, err)

    all_themes: list[ThemeInference] = []
    tracker = None
    for tagname, codes in codes_by_tag.items():
        # Step 1: Auto-assign high-similarity codes to existing themes
        if skip_auto_assign:
            auto_assigned: list[_CodeRow] = []
            pending: list[_CodeRow] = codes
        else:
            auto_assigned, pending = _auto_assign_codes_to_themes(con, tagname, codes)

        logger.info(
            "Tag '%s': %d auto-assigned, %d pending for LLM",
            tagname,
            len(auto_assigned),
            len(pending),
        )

        # Step 2: LLM for remaining codes
        if pending:
            batches = group_by_tag(pending, max_per_batch=5, prefix="theme")
            logger.info(
                "Tag '%s': %d codes -> %d batch(es)",
                tagname,
                len(pending),
                len(batches),
            )
            tag_themes, trk = run_batches(
                con,
                batches,
                _process_theme_batch,
                STAGE_THEME,
                failure_fn,
                progress_callback=progress_callback,
            )
            all_themes.extend(tag_themes)
            tracker = trk

    _log_theme_summary(start_time, all_themes, tracker)
    return all_themes
