"""Split action handler for theme review HITL.

``handle_split_theme_regroup`` divides a theme into two by letting the
user select a subset of codes for the first new theme; the remaining
codes form the second.  Both code groups are sent through scoped LLM
theme inference to generate new names and narratives.

The original theme is marked ``superseded`` and ``derived-from`` edges
link it to the two new nodes.
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


def _build_merged_info(
    first_code_ids: list[int],
    second_code_ids: list[int],
) -> dict:
    """Build the ``data_json`` merge metadata for the superseded theme."""
    return {
        "merged_info": {
            "split_first_code_ids": first_code_ids,
            "split_second_code_ids": second_code_ids,
        }
    }


def handle_split_theme_regroup(
    con: duckdb.DuckDBPyConnection,
    theme: dict,
    first_code_ids: list[int],
    second_code_ids: list[int],
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Split *theme* into two new themes by regrouping codes.

    The original theme is marked ``superseded``.  The codes in both
    groups are sent through scoped LLM theme inference (with auto-assign
    disabled) to generate new names and narratives.

    Args:
        con: Active DuckDB connection.
        theme: Original theme dict (expects keys ``id``, ``name``,
            ``narrative``, ``tag``, ``data_json``).
        first_code_ids: Code IDs for the first new theme.
        second_code_ids: Code IDs for the second new theme.
        db_path: Optional DuckDB path for graph module.

    Returns:
        Tuple of ``(first_new_id, second_new_id)``.

    Raises:
        ValueError: If either code ID list is empty.
    """
    source_id = theme["id"]
    tag = theme.get("tag", "")

    if not first_code_ids or not second_code_ids:
        raise ValueError("Both split themes must have at least one code.")

    db_path = db_path or DEFAULT_DB_PATH
    all_code_ids = first_code_ids + second_code_ids

    # ── Step 1: Mark original as superseded ────────────────────────
    dj = theme.get("data_json") or {}
    dj.update(_build_merged_info(first_code_ids, second_code_ids))

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
                "Theme re-inference produced no results for tag '%s' "
                "(theme %d split)",
                tag,
                source_id,
            )
            rebuild_graph(db_path)
            return -1, -1

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

    if len(node_ids) >= 2:
        return node_ids[0], node_ids[1]
    return node_ids[0], -1
