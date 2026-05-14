"""Merge action handler for code review HITL CLI.

``handle_merge`` redirects ``contains`` edges from source to target,
merges ``data_json`` fields, creates a ``derived-from`` edge, and
rebuilds the in-memory graph.
"""

from pathlib import Path
from typing import Optional

import duckdb
from graph import create_edge, rebuild_graph
from graph.queries import get_node
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .code_review_actions import _update_node_data_json, _update_node_status
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_merge"]


def handle_merge(
    con: duckdb.DuckDBPyConnection,
    source_code: dict,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Merge *source_code* into the code identified by *target_id*.

    Steps:
        1. Redirect ``contains`` edges from source to target
        2. Merge ``data_json`` (exemplar_ids, supporting_quotes)
        3. Clear source's data_json exemplar references
        4. Mark source as ``merged``
        5. Create ``derived-from`` edge: source → target
        6. Rebuild the in-memory graph
    """
    source_id = source_code["id"]

    if source_id == target_id:
        logger.warning("Merge aborted: cannot merge code with itself")
        return

    # 1. Redirect contains edges
    source_edges = con.execute(
        "SELECT target_id FROM edges " "WHERE source_id = ? AND edge_type = 'contains'",
        [source_id],
    ).fetchall()

    for (exemplar_id,) in source_edges:
        already_connected = con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
            [target_id, exemplar_id],
        ).fetchone()

        if already_connected:
            con.execute(
                "DELETE FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
                [source_id, exemplar_id],
            )
        else:
            con.execute(
                "UPDATE edges SET source_id = ? "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
                [target_id, source_id, exemplar_id],
            )

    # 2. Merge data_json
    src_dj = source_code.get("data_json") or {}
    tgt_node = get_node(target_id, db_path=db_path)
    tgt_dj = tgt_node.get("data_json") or {}

    src_eids = src_dj.get("exemplar_ids", [])
    src_quotes = src_dj.get("supporting_quotes", {})
    tgt_eids = tgt_dj.get("exemplar_ids", [])
    tgt_quotes = tgt_dj.get("supporting_quotes", {})

    tgt_dj["exemplar_ids"] = list(dict.fromkeys(tgt_eids + src_eids))
    tgt_dj["supporting_quotes"] = {**src_quotes, **tgt_quotes}
    _update_node_data_json(con, target_id, tgt_dj, db_path=db_path)

    # 3. Clear source's exemplar references
    src_dj.pop("exemplar_ids", None)
    src_dj.pop("supporting_quotes", None)
    _update_node_data_json(con, source_id, src_dj, db_path=db_path)

    # 4. Mark source as merged
    _update_node_status(con, source_id, "merged", db_path=db_path)

    # 5. Create derived-from edge
    create_edge(
        source_id=source_id,
        target_id=target_id,
        edge_type="derived-from",
        db_path=db_path,
    )

    # 6. Rebuild graph
    rebuild_graph(db_path)

    log_user_action(
        con,
        "merge",
        source_id,
        old_value={"status": "draft", "merged_into": None},
        new_value={"status": "merged", "merged_into": target_id},
    )
    increment_user_action_count(con)
