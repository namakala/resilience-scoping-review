"""Batch LLM inference service to generate codes from exemplars.

Groups pending exemplars by tag into batches, renders prompts with ontology
context and existing codes, calls Groq with retry logic, parses structured
responses, updates inference status, and returns CodeInference objects.

Auto-assignment guardrail
-------------------------
Before sending exemplars to the LLM, each exemplar is scored against
existing codes (draft + approved) using a hybrid metric:

    0.6 * cosine(exemplar_emb, code_emb)
  + 0.2 * direct_BM25(exemplar_content, code_name+definition)
  + 0.2 * indirect_exemplar_agreement

Exemplars scoring above ``SIMILARITY_SCORE_THRESHOLD`` (default 0.8) are
automatically assigned to the best-matching existing code inside an atomic
``graph_transaction``, skipping LLM inference entirely.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import polars as pl
from config import (
    code_model,
    code_temperature,
    exemplar_similarity_threshold,
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
    similarity_score_threshold,
)
from graph import get_nodes_by_type_and_tag, graph_transaction
from inference.status_updates import mark_success
from persistence.duckdb_connection import DEFAULT_DB_PATH
from persistence.embedding_cache import get_embedding
from persistence.loaders import load_exemplars
from utils.logging import get_logger

from .batch_processor import record_tokens, run_batches
from .batching import Batch, group_by_similarity, group_by_tag, group_items_by_tag
from .exemplar_clustering import cluster_by_similarity, compute_pairwise_similarity
from .fewshot_loader import load_fewshot
from .inference_status_crud import set_status
from .inference_status_queries import get_pending_items
from .inference_status_types import GENERATED, STAGE_CODE
from .parsing import CodeInference, parse_code_response
from .prompts import PromptBundle, render_code_prompt
from .retry import infer_batch_with_retry
from .status_updates import mark_failure
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


def _get_all_existing_codes(
    tag: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Load codes from the current tag and all other tags.

    Includes codes with ``status IN ('draft', 'approved')``.  Excludes
    ``rejected`` and ``merged`` (orphaned nodes).  Returns a dict:

    ``{'same_tag': [...], 'other_tags': {'TagName': [...], ...}}``
    """
    all_nodes = get_nodes_by_type_and_tag("code", None, db_path=db_path)
    active = [n for n in all_nodes if n.get("status") in ("draft", "approved")]

    def _to_entry(n: dict) -> dict[str, str]:
        return {"name": n["name"], "definition": n["definition"]}

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

    logger.debug(
        "Found %d active codes for tag '%s' and %d other tags",
        len(same_tag),
        tag,
        len(other_tags),
    )
    return {"same_tag": same_tag, "other_tags": other_tags}


# Backward-compatible alias for existing tests
def _get_existing_codes_for_tag(tag, db_path=None):
    return _get_all_existing_codes(tag, db_path)["same_tag"]


# ── Auto-assignment Guardrail ─────────────────────────────────────────────


def _load_embeddings_bulk(
    con: duckdb.DuckDBPyConnection,
    entity_ids: list[int],
    entity_type: str,
) -> tuple[list[int], np.ndarray]:
    """Load cached embeddings for a list of entity IDs.

    Returns (present_ids, stacked_embeddings).  Missing IDs are silently
    dropped.  Raises ``ValueError`` if no embeddings found.
    """
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


def _auto_assign_exemplars(
    con: duckdb.DuckDBPyConnection,
    tag: str,
    exemplars: list[_ExemplarRow],
    db_path: Path | None = None,
) -> tuple[list[_ExemplarRow], list[_ExemplarRow]]:
    """Auto-assign exemplars to existing codes based on hybrid similarity.

    Exemplars whose combined score (cosine + direct BM25 + indirect exemplar
    agreement) exceeds ``SIMILARITY_SCORE_THRESHOLD`` are assigned to the
    best-matching code inside an atomic ``graph_transaction``.

    Returns
    -------
    tuple[list[_ExemplarRow], list[_ExemplarRow]]
        ``(auto_assigned, remaining)``.
    """
    if not exemplars:
        return [], []

    threshold = similarity_score_threshold()

    # 1. Load existing codes for this tag (draft + approved)
    all_nodes = get_nodes_by_type_and_tag("code", tag, db_path=db_path)
    candidate_codes = [n for n in all_nodes if n.get("status") in ("draft", "approved")]
    if not candidate_codes:
        logger.info("No existing codes for tag '%s' — skipping auto-assign", tag)
        return [], exemplars

    # 2. Build data structures
    code_ids = [n["id"] for n in candidate_codes]
    code_texts = [
        f"{n.get('name', '')} {n.get('definition', '')}" for n in candidate_codes
    ]
    code_exemplar_map: dict[int, set[int]] = {}
    for n in candidate_codes:
        dj = n.get("data_json") or {}
        eids = dj.get("exemplar_ids") or []
        code_exemplar_map[n["id"]] = {int(e) for e in eids}

    exemplar_ids = [e.id for e in exemplars]
    exemplar_texts = [f"{e.content} {' '.join(e.keywords)}" for e in exemplars]

    # 3. Load embeddings
    try:
        _, ex_embs = _load_embeddings_bulk(con, exemplar_ids, "exemplar")
        _, cd_embs = _load_embeddings_bulk(con, code_ids, "code")
    except ValueError as exc:
        logger.warning("Embedding loading failed for auto-assign: %s", exc)
        return [], exemplars

    # Collect embeddings for the indirect signal: exemplars linked to codes
    all_linked_ids = sorted(set().union(*code_exemplar_map.values()))
    if all_linked_ids:
        # Load embeddings for linked exemplars individually (handles missing)
        present_linked: list[int] = []
        linked_embs_list: list[np.ndarray] = []
        for eid in all_linked_ids:
            emb = get_embedding(con, str(eid), "exemplar")
            if emb is not None:
                present_linked.append(eid)
                linked_embs_list.append(emb)
        if present_linked:
            linked_ex_embs = np.stack(linked_embs_list, axis=0)
        else:
            present_linked, linked_ex_embs = [], np.zeros((0, 384), dtype="float32")
    else:
        present_linked, linked_ex_embs = [], np.zeros((0, 384), dtype="float32")

    # Build a restricted exemplar space for indirect scoring: only linked ones
    restricted_exemplar_ids = present_linked if present_linked else []
    restricted_exemplar_embs = (
        linked_ex_embs if present_linked else np.zeros((0, 384), dtype="float32")
    )

    # 4. Compute hybrid scores
    from semantic.similarity import compute_hybrid_autoassign_scores

    tokenizer = _get_tokenizer()
    scores = compute_hybrid_autoassign_scores(
        exemplar_embeddings=ex_embs,
        exemplar_texts=exemplar_texts,
        code_embeddings=cd_embs,
        code_texts=code_texts,
        code_exemplar_map=code_exemplar_map,
        all_exemplar_ids=restricted_exemplar_ids,
        all_exemplar_embeddings=restricted_exemplar_embs,
        tokenizer=tokenizer,
        emb_weight=0.6,
        direct_bm25_weight=0.2,
        indirect_weight=0.2,
        top_k=20,
    )

    # 5. Find best matches above threshold
    best_code_idx = scores.argmax(axis=1)  # (n,)
    best_scores = scores.max(axis=1)  # (n,)

    auto_idxs = np.where(best_scores >= threshold)[0]
    if len(auto_idxs) == 0:
        logger.info(
            "No exemplars above threshold=%.2f for tag '%s' — all proceed to LLM",
            threshold,
            tag,
        )
        return [], exemplars

    auto_assigned: list[int] = []
    remaining: list[_ExemplarRow] = []
    for i, ex in enumerate(exemplars):
        if i in auto_idxs:
            auto_assigned.append(ex.id)
        else:
            remaining.append(ex)

    logger.info(
        "Auto-assigned %d / %d exemplars for tag '%s' (threshold=%.2f)",
        len(auto_assigned),
        len(exemplars),
        tag,
        threshold,
    )

    # 6. Persist inside atomic transaction
    with graph_transaction(db_path=db_path):
        for i in auto_idxs:
            ex = exemplars[i]
            cid = code_ids[best_code_idx[i]]

            # Fetch existing data_json
            from graph import get_node

            existing = get_node(cid, db_path=db_path)
            old_dj = existing.get("data_json") or {}
            old_eids = set(old_dj.get("exemplar_ids") or [])
            old_quotes = old_dj.get("supporting_quotes") or {}

            eid_str = str(ex.id)
            if eid_str in old_eids:
                logger.debug(
                    "Exemplar %s already linked to code %s — skipping",
                    eid_str,
                    cid,
                )
                continue

            # Read exemplar content for supporting_quote
            ex_row = (
                load_exemplars()
                .filter(pl.col("id") == ex.id)
                .select("content")
                .collect()
            )
            quote = ex_row["content"][0] if ex_row.height > 0 else ""

            new_eids = list(old_eids | {eid_str})
            new_quotes = {**old_quotes, eid_str: quote}

            merged_dj = {
                "exemplar_ids": new_eids,
                "supporting_quotes": new_quotes,
                "related_existing_codes": old_dj.get("related_existing_codes", []),
            }

            # Update code node data_json
            from graph.transactions import get_active_connection

            tx_con = get_active_connection()
            if tx_con is None:
                raise RuntimeError("Auto-assign requires an active graph_transaction")
            tx_con.execute(
                "UPDATE nodes SET data_json = ? WHERE id = ?",
                [json.dumps(merged_dj, ensure_ascii=False), cid],
            )

            # Update in-memory graph
            from graph import get_graph

            G = get_graph(db_path)
            attrs = dict(G.nodes[cid])
            attrs["data_json"] = merged_dj
            G.add_node(cid, **attrs)

            # Create contains edge from code to exemplar
            from graph import create_edge
            from inference.exemplar_node_creation import ensure_exemplar_nodes

            enm = ensure_exemplar_nodes(con, {eid_str}, tag, db_path=db_path)
            if eid_str in enm:
                create_edge(
                    source_id=cid,
                    target_id=enm[eid_str],
                    edge_type="contains",
                    db_path=db_path,
                )

            # Mark inference_status as generated (within transaction)
            from graph.transactions import get_active_connection as get_tx_con

            tx_con2 = get_tx_con()
            if tx_con2 is not None:
                set_status(
                    tx_con2,
                    entity_id=eid_str,
                    entity_type="exemplar",
                    stage=STAGE_CODE,
                    status=GENERATED,
                )

    return [e for e in exemplars if e.id in auto_assigned], remaining


# ── Existing helper functions ────────────────────────────────────────────


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
    other_tag_codes: dict[str, list[dict[str, str]]] | None = None,
) -> PromptBundle:
    return render_code_prompt(
        fewshot=fewshot,
        ontology_path=ontology_path,
        tag_description=tag_description,
        existing_codes=existing_codes,
        other_tag_codes=other_tag_codes or {},
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
    existing_info = _get_all_existing_codes(batch.tag)
    existing_codes = existing_info["same_tag"]
    other_tag_codes = existing_info["other_tags"]

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
            other_tag_codes=other_tag_codes,
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
            c.supporting_quote = item.content  # fill from actual exemplar content
            mark_success(con, item.id, "exemplar", "code")
            results.append(c)
        else:
            mark_failure(con, item.id, "No code generated by LLM")
    return results


def infer_codes(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
    tags: list[str] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
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

    # Group by tag for per-tag auto-assignment
    by_tag = group_items_by_tag(exemplars)
    all_results: list[CodeInference] = []
    tracker = None

    for tg, tg_exemplars in by_tag.items():
        # Step 1: Auto-assign high-similarity exemplars to existing codes
        auto_assigned, pending = _auto_assign_exemplars(
            con,
            tg,
            tg_exemplars,
            db_path=DEFAULT_DB_PATH,
        )

        logger.info(
            "Tag '%s': %d auto-assigned, %d pending for LLM",
            tg,
            len(auto_assigned),
            len(pending),
        )

        # Step 2: LLM for remaining exemplars — similarity-based clustering
        if pending:
            try:
                sim_matrix = compute_pairwise_similarity(pending, con)
                cluster_groups, misc_group = cluster_by_similarity(
                    pending,
                    sim_matrix,
                    threshold=exemplar_similarity_threshold(),
                    min_cluster_size=5,
                )
                batches = group_by_similarity(
                    tg, cluster_groups, misc_group, prefix="code"
                )
                logger.info(
                    "Tag '%s': %d cluster batch(es), %d misc (total %d pending)",
                    tg,
                    len(cluster_groups),
                    1 if misc_group else 0,
                    len(pending),
                )
            except ValueError as exc:
                logger.warning(
                    "Similarity clustering failed for tag '%s': %s — "
                    "falling back to count-based batching (max 15)",
                    tg,
                    exc,
                )
                batches = group_by_tag(pending, max_per_batch=15, prefix="code")

            def failure_fn(c, item, err):
                mark_failure(c, item.id, err)

            results, trk = run_batches(
                con,
                batches,
                _process_code_batch,
                STAGE_CODE,
                failure_fn,
                progress_callback=progress_callback,
            )
            all_results.extend(results)
            tracker = trk

    _log_code_summary(start_time, all_results, tracker)
    return all_results
