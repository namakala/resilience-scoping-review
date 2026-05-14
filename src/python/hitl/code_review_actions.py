"""Simple action handlers for code review HITL CLI.

Provides ``handle_approve``, ``handle_edit``, ``handle_reject``, and
``handle_defer`` plus private helpers for node updates.
(``handle_merge`` lives in ``code_review_merge.py``.)
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import sync_node
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import APPROVED, ENTITY_CODE, REJECTED, STAGE_CODE
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .edits import invalidate_code_embedding
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = [
    "handle_approve",
    "handle_edit",
    "handle_reject",
    "handle_defer",
]


# ── Node update helpers (used internally and by code_review_merge) ──


def _update_node_status(
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


def _update_node_definition(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_definition: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node definition and reset status to draft, then sync graph."""
    con.execute(
        "UPDATE nodes SET definition = ?, status = 'draft', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_definition, node_id],
    )
    sync_node(node_id, db_path)


def _update_node_data_json(
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


# ── Action handlers ─────────────────────────────────────────────────


def handle_approve(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Approve a code: set node status and inference status to approved."""
    node_id = code["id"]
    _update_node_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_CODE,
        stage=STAGE_CODE,
        status=APPROVED,
    )
    log_user_action(con, "approve", node_id)
    increment_user_action_count(con)


def handle_edit(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
    new_definition: str = "",
) -> None:
    """Edit a code definition: update text, reset to draft, invalidate cache."""
    node_id = code["id"]
    old_def = code.get("definition", "")

    if not new_definition.strip():
        logger.warning("Edit aborted: empty definition")
        return

    if new_definition == old_def:
        logger.info("Edit aborted: definition unchanged")
        return

    _update_node_definition(con, node_id, new_definition, db_path=db_path)
    set_status_draft(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_CODE,
        stage=STAGE_CODE,
    )
    invalidate_code_embedding(con, node_id, code.get("tag", ""))
    log_user_action(
        con,
        "edit",
        node_id,
        old_value={"definition": old_def},
        new_value={"definition": new_definition},
    )
    increment_user_action_count(con)


def handle_reject(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject a code: set node status and inference status to rejected."""
    node_id = code["id"]
    _update_node_status(con, node_id, "rejected", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_CODE,
        stage=STAGE_CODE,
        status=REJECTED,
    )
    log_user_action(con, "reject", node_id)
    increment_user_action_count(con)


def handle_defer(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Defer a code: log action only, no status change."""
    log_user_action(con, "defer", code["id"])
    increment_user_action_count(con)
