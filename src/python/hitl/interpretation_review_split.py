"""Split action handler for interpretation review HITL CLI.

``handle_split_interpretation`` divides an interpretation into two by
letting the user select a subset of themes for the first new
interpretation; the remaining themes form the second. Both new
interpretations must have contiguous ``tag_spans``. The original
interpretation is marked ``merged`` with ``derived-from`` edges to the
new nodes. All changes are atomic within a single DuckDB transaction.
"""

import copy
import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import clear_traversal_cache, create_edge, create_node, rebuild_graph
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from ontology import is_contiguous_subtree
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_split_interpretation"]


def _compute_tag_spans(
    theme_ids: list[int],
    con: duckdb.DuckDBPyConnection,
) -> set[str]:
    """Compute the union of tags for a set of themes.

    Each theme's tag is looked up from the nodes table.
    """
    tags: set[str] = set()
    for tid in theme_ids:
        row = con.execute("SELECT tag FROM nodes WHERE id = ?", [tid]).fetchone()
        if row:
            tags.add(str(row[0]))
    return tags


def _build_data_json(tag_spans: set[str]) -> dict[str, Any]:
    """Build the ``data_json`` payload dict for an interpretation node."""
    return {"tag_spans": sorted(tag_spans)}


def handle_split_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    first_theme_ids: list[int],
    second_theme_ids: list[int],
    first_name: str,
    second_name: str,
    first_narrative: str,
    second_narrative: str,
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Split *interp* into two new interpretations.

    The original interpretation is marked ``merged``. Two new
    interpretation nodes are created as ``draft`` with ``spans`` edges
    to their respective themes. ``derived-from`` edges link the original
    to both new nodes.

    Args:
        con: Active DuckDB connection.
        interp: Original interpretation dict (expects keys ``id``,
            ``name``, ``narrative``, ``tag``, ``data_json``).
        first_theme_ids: Theme IDs for the first new interpretation.
        second_theme_ids: Theme IDs for the second new interpretation.
        first_name: Name for the first new interpretation.
        second_name: Name for the second new interpretation.
        first_narrative: Narrative for the first new interpretation.
        second_narrative: Narrative for the second new interpretation.
        db_path: Optional DuckDB path for graph module.

    Returns:
        Tuple of ``(first_new_id, second_new_id)``.

    Raises:
        ValueError: If either theme list is empty or tag_spans are
            non-contiguous.
    """
    source_id = interp["id"]

    if not first_theme_ids or not second_theme_ids:
        raise ValueError("Both split interpretations must have at least one theme.")

    # Compute and validate tag_spans for both branches
    first_tags = _compute_tag_spans(first_theme_ids, con)
    second_tags = _compute_tag_spans(second_theme_ids, con)

    if len(first_tags) > 1 and not is_contiguous_subtree(first_tags):
        raise ValueError(
            f"First split has non-contiguous tag_spans: {sorted(first_tags)}"
        )
    if len(second_tags) > 1 and not is_contiguous_subtree(second_tags):
        raise ValueError(
            f"Second split has non-contiguous tag_spans: {sorted(second_tags)}"
        )

    # Determine root tags (first tag alphabetically as fallback)
    first_root = sorted(first_tags)[0] if first_tags else interp.get("tag", "")
    second_root = sorted(second_tags)[0] if second_tags else interp.get("tag", "")

    G = get_graph(db_path)
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        # Mark original as merged
        dj = interp.get("data_json") or {}
        dj["merged_info"] = {
            "split_into_first_name": first_name,
            "split_into_second_name": second_name,
        }
        con.execute(
            "UPDATE nodes SET status = 'merged', data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(dj, ensure_ascii=False), source_id],
        )

        # Create first new interpretation
        first_id = create_node(
            node_type="interpretation",
            name=first_name,
            definition=first_narrative,
            tag=first_root,
            status="draft",
            data_json=_build_data_json(first_tags),
            db_path=db_path,
        )

        # Create second new interpretation
        second_id = create_node(
            node_type="interpretation",
            name=second_name,
            definition=second_narrative,
            tag=second_root,
            status="draft",
            data_json=_build_data_json(second_tags),
            db_path=db_path,
        )

        # Delete existing spans edges from original
        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND edge_type = 'spans'",
            [source_id],
        )

        # Create new spans edges
        for tid in first_theme_ids:
            create_edge(
                source_id=first_id,
                target_id=tid,
                edge_type="spans",
                db_path=db_path,
            )
        for tid in second_theme_ids:
            create_edge(
                source_id=second_id,
                target_id=tid,
                edge_type="spans",
                db_path=db_path,
            )

        # Create derived-from edges
        create_edge(
            source_id=source_id,
            target_id=first_id,
            edge_type="derived-from",
            db_path=db_path,
        )
        create_edge(
            source_id=source_id,
            target_id=second_id,
            edge_type="derived-from",
            db_path=db_path,
        )

        log_user_action(
            con,
            "split",
            source_id,
            old_value={
                "status": interp.get("status", "draft"),
                "theme_ids": first_theme_ids + second_theme_ids,
            },
            new_value={
                "status": "merged",
                "split_into": [first_id, second_id],
            },
        )
        committed = True
        con.execute("COMMIT")
        increment_user_action_count(con)

    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning("Rollback failed; transaction may already be closed")
        raise

    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    rebuild_graph(db_path)

    logger.info(
        "Interpretation %d split into %d and %d",
        source_id,
        first_id,
        second_id,
    )

    return first_id, second_id
