"""Convert ``InterpretationInference`` results into graph interpretation nodes.

Creates interpretation nodes (type='interpretation', status='draft') with
``tag_spans`` in ``data_json``, ``spans`` edges to constituent themes,
and ``derived-from`` edges on re-synthesis. All writes within a single
:class:`~graph.transactions.graph_transaction` for atomicity.

Usage:
    from inference.interpretation_creation import create_interpretation_nodes
    node_ids = create_interpretation_nodes(con, synthesize_interpretations(con))
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
from graph import create_edge, create_node, get_nodes_by_type_and_tag, graph_transaction
from ontology import invalidate_cache_for_tags, is_contiguous_subtree
from utils.logging import get_logger

from .inference_status_crud import set_status
from .inference_status_types import (
    ENTITY_INTERPRETATION,
    GENERATED,
    STAGE_INTERPRETATION,
)
from .interpretation_node_reinfer import (
    load_existing_draft_interpretations,
    rename_node_raw,
)
from .interpretation_tag_utils import compute_tag_spans
from .name_utils import check_duplicate_names, make_unique_name
from .parsing import InterpretationInference

logger = get_logger(__name__)

__all__ = ["create_interpretation_nodes"]


def _load_all_interpretation_names(
    db_path: Optional[Path] = None,
) -> set[str]:
    """Fetch ALL existing interpretation node names across all tags.

    Used for cross-tag collision detection.
    """
    nodes = get_nodes_by_type_and_tag("interpretation", None, db_path=db_path)
    return {n["name"] for n in nodes}


def _build_data_json(tag_spans: set[str]) -> dict:
    """Build the ``data_json`` payload for an interpretation node."""
    return {"tag_spans": sorted(tag_spans)}


def create_interpretation_nodes(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[InterpretationInference],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Convert *interpretations* into graph nodes with ``spans`` edges.

    Resolves theme IDs to tags (``tag_spans``), validates contiguity,
    creates interpretation nodes + edges, handles re-synthesis via
    ``derived-from``, and invalidates caches for all spanned tags.

    Args:
        con: Active DuckDB connection.
        interpretations: List of :class:`InterpretationInference` items.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of created interpretation node IDs in input order.

    Raises:
        ValueError: If empty, missing name, or non-contiguous tag_spans.
        KeyError: If a referenced theme ID does not exist.
    """
    # ── Input validation ───────────────────────────────────────────────
    if not interpretations:
        logger.warning("create_interpretation_nodes called with empty list; no-op")
        return []

    for interp in interpretations:
        if not interp.interpretation_name:
            raise ValueError(
                f"InterpretationInference has empty interpretation_name: {interp}"
            )
        if not interp.theme_ids:
            logger.warning(
                "Interpretation '%s' has no theme_ids; creating node anyway",
                interp.interpretation_name,
            )

    check_duplicate_names(
        interpretations,
        lambda i: i.interpretation_name,
        entity_type="interpretation",
    )

    # ── Pre-transaction: compute + validate tag_spans ──────────────────
    tag_span_map = compute_tag_spans(interpretations, db_path=db_path)

    for interp in interpretations:
        tag_spans, _ = tag_span_map[interp.interpretation_name]
        if len(tag_spans) > 1 and not is_contiguous_subtree(tag_spans):
            raise ValueError(
                f"Interpretation '{interp.interpretation_name}' has "
                f"non-contiguous tag_spans: {sorted(tag_spans)}"
            )

    # ── Pre-transaction: detect re-synthesis candidates ────────────────
    existing_draft = load_existing_draft_interpretations(db_path=db_path)
    superseded_names: set[str] = {
        i.interpretation_name
        for i in interpretations
        if i.interpretation_name in existing_draft
    }
    used_names: set[str] = {n for n in existing_draft if n not in superseded_names}

    logger.info(
        "Creating %d interpretation nodes%s",
        len(interpretations),
        f" ({len(superseded_names)} re-synthesized)" if superseded_names else "",
    )

    # ── Transaction: rename superseded + create new ────────────────────
    node_ids: list[int] = []
    all_span_tags: set[str] = set()

    with graph_transaction(db_path=db_path):
        for interp in interpretations:
            if interp.interpretation_name in superseded_names:
                old_id = existing_draft[interp.interpretation_name]
                rename_node_raw(
                    old_id,
                    f"{interp.interpretation_name}_deprecated_{old_id}",
                    db_path=db_path,
                )

        for interp in interpretations:
            _, root_tag = tag_span_map[interp.interpretation_name]
            unique_name = make_unique_name(
                interp.interpretation_name, used_names, entity_type="interpretation"
            )

            # Cross-tag collision safety net: only check OTHER tags
            other_tag_interp_names = set()
            for n in get_nodes_by_type_and_tag("interpretation", None, db_path=db_path):
                t = n.get("tag")
                if t != root_tag and n.get("status") in ("draft", "approved"):
                    other_tag_interp_names.add(n["name"])
            other_tag_interp_names -= superseded_names
            if unique_name in other_tag_interp_names:
                qualified = f"{unique_name} [span]"
                logger.warning(
                    "Cross-tag interpretation name collision '%s' resolved to '%s'",
                    unique_name,
                    qualified,
                )
                unique_name = make_unique_name(qualified, other_tag_interp_names)

            used_names.add(unique_name)

            tag_spans, root_tag = tag_span_map[interp.interpretation_name]
            all_span_tags.update(tag_spans)

            node_id = create_node(
                node_type="interpretation",
                name=unique_name,
                definition=interp.narrative,
                tag=root_tag,
                status="draft",
                data_json=_build_data_json(tag_spans),
                db_path=db_path,
            )
            node_ids.append(node_id)

            prev_id = existing_draft.get(interp.interpretation_name)
            if prev_id is not None:
                create_edge(
                    source_id=prev_id,
                    target_id=node_id,
                    edge_type="derived-from",
                    db_path=db_path,
                )

            for theme_id_str in interp.theme_ids:
                try:
                    clean_id = "".join(c for c in theme_id_str if c.isdigit())
                    if not clean_id:
                        raise ValueError(f"No digits in '{theme_id_str}'")
                    theme_id = int(clean_id)
                except (ValueError, TypeError):
                    logger.error(
                        "Invalid theme_id '%s' in interpretation '%s'; skipping edge",
                        theme_id_str,
                        interp.interpretation_name,
                    )
                    continue
                create_edge(
                    source_id=node_id,
                    target_id=theme_id,
                    edge_type="spans",
                    db_path=db_path,
                )

    # ── Post-transaction: update inference_status ──────────────────────
    for node_id in node_ids:
        set_status(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_INTERPRETATION,
            stage=STAGE_INTERPRETATION,
            status=GENERATED,
        )

    # ── Post-transaction: invalidate caches ────────────────────────────
    if all_span_tags:
        try:
            invalidate_cache_for_tags(
                list(all_span_tags), db_path=db_path, reason="interpretation-creation"
            )
        except Exception:
            logger.warning(
                "Cache invalidation failed for tags %s; continuing",
                sorted(all_span_tags),
            )

    logger.info(
        "Created %d interpretation nodes spanning tags %s",
        len(node_ids),
        sorted(all_span_tags),
    )
    return node_ids
