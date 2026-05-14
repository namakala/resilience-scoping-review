"""Simple action handlers for theme review HITL CLI.

Provides ``handle_approve_theme``, ``handle_edit_theme``,
``handle_reject_theme``, and ``handle_defer_theme`` plus private
helpers for node updates.  (``handle_merge_themes`` lives in
``theme_review_merge.py``.)
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import create_edge, rebuild_graph, sync_node
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import (
    APPROVED,
    ENTITY_THEME,
    REJECTED,
    STAGE_THEME,
)
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .edits import invalidate_theme_embedding
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = [
    "handle_approve_theme",
    "handle_edit_theme",
    "handle_reject_theme",
    "handle_defer_theme",
]


# ── Node update helpers ────────────────────────────────────────────


def _update_theme_status(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_status: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node status in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_status, node_id],
    )
    sync_node(node_id, db_path)


def _update_theme_narrative(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_narrative: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node narrative (stored in ``definition``) and reset status to draft."""
    con.execute(
        "UPDATE nodes SET definition = ?, status = 'draft', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_narrative, node_id],
    )
    sync_node(node_id, db_path)


def _update_theme_data_json(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_data_json: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Update node data_json in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(new_data_json, ensure_ascii=False), node_id],
    )
    sync_node(node_id, db_path)


def _update_theme_codes(
    con: duckdb.DuckDBPyConnection,
    theme_id: int,
    code_ids: list[int],
    db_path: Optional[Path] = None,
) -> None:
    """Replace ``composed-of`` edges for a theme with a new set of codes.

    Deletes all existing ``composed-of`` edges from the theme, then
    creates new edges for each *code_id*.  Rebuilds the in-memory graph
    at the end for consistency.
    """
    con.execute(
        "DELETE FROM edges WHERE source_id = ? AND edge_type = 'composed-of'",
        [theme_id],
    )
    for cid in code_ids:
        create_edge(
            source_id=theme_id,
            target_id=cid,
            edge_type="composed-of",
            db_path=db_path,
        )
    rebuild_graph(db_path)


# ── Action handlers ────────────────────────────────────────────────


def handle_approve_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Approve a theme: validate constraints, set status and inference status.

    Checks ADR-013 constraints via ``validate_constraint`` before
    approving.  If constraints fail, prints error and returns without
    modifying state.
    """
    node_id = theme["id"]

    try:
        from ontology import ConstraintError, validate_constraint

        validate_constraint({"id": node_id, "type": "theme"}, "approve")
    except ConstraintError as exc:
        from .theme_review_display import console

        console.print(f"[red]Constraint violation: {exc}[/red]")
        logger.warning(
            "Theme approve rejected by constraint", extra={"error": str(exc)}
        )
        return

    _update_theme_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
        status=APPROVED,
    )
    log_user_action(con, "approve", node_id)
    increment_user_action_count(con)


def handle_edit_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
    db_path: Optional[Path] = None,
    new_narrative: str = "",
    new_code_ids: Optional[list[int]] = None,
) -> None:
    """Edit a theme: update narrative and optionally codes, reset to draft.

    Args:
        con: Active DuckDB connection.
        theme: Theme dict (expects keys ``id``, ``name``, ``narrative``, ``tag``).
        db_path: Optional DuckDB path for graph module.
        new_narrative: Updated narrative text.
        new_code_ids: Optional updated list of constituent code IDs.
            ``None`` means codes are unchanged.
    """
    node_id = theme["id"]
    old_narrative = theme.get("narrative", "")

    if not new_narrative.strip():
        logger.warning("Edit aborted: empty narrative")
        return

    if new_narrative == old_narrative and new_code_ids is None:
        logger.info("Edit aborted: narrative unchanged and no code changes")
        return

    old_data_json = theme.get("data_json") or {}

    _update_theme_narrative(con, node_id, new_narrative, db_path=db_path)

    if new_code_ids is not None:
        _update_theme_codes(con, node_id, new_code_ids, db_path=db_path)
        updated_data_json = {**old_data_json, "code_ids": new_code_ids}
        _update_theme_data_json(con, node_id, updated_data_json, db_path=db_path)

    set_status_draft(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
    )
    invalidate_theme_embedding(con, node_id, theme.get("tag", ""))
    log_user_action(
        con,
        "edit",
        node_id,
        old_value={"narrative": old_narrative},
        new_value={"narrative": new_narrative},
    )
    increment_user_action_count(con)


def handle_reject_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject a theme: set node status and inference status to rejected."""
    node_id = theme["id"]
    _update_theme_status(con, node_id, "rejected", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
        status=REJECTED,
    )
    log_user_action(con, "reject", node_id)
    increment_user_action_count(con)


def handle_defer_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
) -> None:
    """Defer a theme: log action only, no status change."""
    log_user_action(con, "defer", theme["id"])
    increment_user_action_count(con)
