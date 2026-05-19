"""Split action handler for theme review HITL.

``handle_split_theme_regroup`` divides a theme into N new themes by
letting the user iteratively select subsets of codes. Each selected
subset forms one group. All groups are sent through scoped LLM theme
inference to generate new names and narratives.

The original theme is marked ``superseded`` and ``derived-from`` edges
link it to all new nodes.
"""

import copy
import json
from pathlib import Path
from typing import Optional

import duckdb
from graph import clear_traversal_cache, rebuild_graph
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from inference.create_theme_nodes import create_theme_nodes
from inference.theme_inference import infer_themes
from persistence.duckdb_connection import DEFAULT_DB_PATH
from persistence.state_updates import increment_user_action_count
from semantic.embedding_generation import generate_theme_embeddings
from utils.logging import get_logger

from .invalidation import invalidate_interpretations
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_split_theme_regroup"]


def _build_merged_info(groups: list[list[int]]) -> dict:
    """Build the ``data_json`` merge metadata for the superseded theme."""
    return {
        "merged_info": {
            "split_groups": groups,
        }
    }


def handle_split_theme_regroup(
    con: duckdb.DuckDBPyConnection,
    theme: dict,
    groups: list[list[int]],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Split *theme* into N new themes by regrouping codes.

    The original theme is marked ``superseded``.  The codes in all
    groups are sent through scoped LLM theme inference (with auto-assign
    disabled) to generate new names and narratives.

    Args:
        con: Active DuckDB connection.
        theme: Original theme dict (expects keys ``id``, ``name``,
            ``narrative``, ``tag``, ``data_json``).
        groups: List of code-ID groups. Each group becomes one new
            theme. Must contain at least 2 groups.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of new theme node IDs, one per group.

    Raises:
        ValueError: If fewer than 2 groups, or any group is empty.
    """
    source_id = theme["id"]
    tag = theme.get("tag", "")

    if len(groups) < 2:
        raise ValueError("Split requires at least 2 groups of codes.")
    for i, g in enumerate(groups):
        if not g:
            raise ValueError(f"Group {i+1} must have at least one code.")

    db_path = db_path or DEFAULT_DB_PATH
    all_code_ids = [cid for g in groups for cid in g]

    # ── Step 1: Mark original as superseded ────────────────────────
    dj = theme.get("data_json") or {}
    dj.update(_build_merged_info(groups))

    G = get_graph(db_path)
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        con.execute(
            "UPDATE nodes SET status = 'superseded', data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(dj, ensure_ascii=False), source_id],
        )

        # Delete composed-of edges from original theme to its codes
        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND edge_type = 'composed-of'",
            [source_id],
        )

        # Delete spans edges from interpretations pointing to this theme
        con.execute(
            "DELETE FROM edges WHERE target_id = ? AND edge_type = 'spans'",
            [source_id],
        )

        # Mark downstream interpretations as draft
        interp_ids = con.execute(
            "SELECT DISTINCT source_id FROM edges "
            "WHERE target_id = ? AND edge_type = 'spans'",
            [source_id],
        ).fetchall()
        for (iid,) in interp_ids:
            con.execute(
                "UPDATE nodes SET status = 'draft', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [iid],
            )

        committed = True
        con.execute("COMMIT")

    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning(
                    "Rollback failed during theme split; "
                    "transaction may already be closed"
                )
        raise

    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    # ── Step 2: Re-infer themes via scoped LLM ─────────────────────
    try:
        themes = infer_themes(
            con,
            tag=tag,
            code_ids=all_code_ids,
            skip_auto_assign=True,
        )
        if not themes:
            logger.warning(
                "Theme re-inference produced no results for tag '%s' (theme %d split)",
                tag,
                source_id,
            )
            rebuild_graph(db_path)
            return []

        node_ids = create_theme_nodes(con, themes, tag=tag, db_path=db_path)
        generate_theme_embeddings(con)
    except Exception as exc:
        logger.error(
            "Theme re-inference failed for split (theme %d): %s",
            source_id,
            exc,
        )
        rebuild_graph(db_path)
        raise

    # ── Step 3: Invalidate downstream caches ──────────────────────
    try:
        interp_ids = con.execute(
            "SELECT DISTINCT source_id FROM edges "
            "WHERE target_id IN ("
            "  SELECT id FROM nodes WHERE name LIKE '%' || ? || '%'"
            ") AND edge_type = 'spans'",
            [theme.get("name", "")],
        ).fetchall()
        if interp_ids:
            invalidate_interpretations(con, [r[0] for r in interp_ids])
    except Exception as exc:
        logger.warning(
            "Downstream invalidation failed after theme split: %s",
            exc,
        )

    # ── Step 4: Finalize ──────────────────────────────────────────
    rebuild_graph(db_path)

    log_user_action(
        con,
        "split",
        source_id,
        old_value={
            "status": theme.get("status", "draft"),
            "code_ids": all_code_ids,
        },
        new_value={
            "status": "superseded",
            "split_into": node_ids,
        },
    )
    increment_user_action_count(con)

    logger.info(
        "Theme %d split into %d new themes (node_ids: %s)",
        source_id,
        len(node_ids),
        node_ids,
    )

    return node_ids
