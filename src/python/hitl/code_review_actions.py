"""Simple action handlers for code review HITL CLI.

Provides ``handle_approve``, ``handle_edit``, ``handle_reject``, and
``handle_defer`` plus private helpers for node updates.
(``handle_merge`` lives in ``code_review_merge.py``.)
"""

from pathlib import Path
from typing import Any, Optional

import duckdb
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import APPROVED, ENTITY_CODE, REJECTED, STAGE_CODE
from utils.logging import get_logger

from .invalidation import invalidate_code_embedding
from .shared import (
    _log_and_finish,
    _update_node_definition,
    _update_node_name,
    _update_node_status,
    console,
)

logger = get_logger(__name__)

__all__ = [
    "handle_approve",
    "handle_edit",
    "handle_reject",
    "handle_defer",
]


# ── Action handlers ─────────────────────────────────────────────────


def handle_approve(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Approve a code: validate constraints, set node status and inference status."""
    node_id = code["id"]

    try:
        from ontology import ConstraintError, validate_constraint

        validate_constraint(
            {"id": node_id, "type": "code", "tag": code.get("tag", "")},
            "approve",
        )
    except ConstraintError as exc:
        console.print(f"[red]Constraint violation: {exc}[/red]")
        logger.warning(
            "Code approve rejected by constraint",
            extra={"error": str(exc), "constraint_type": exc.code},
        )
        return

    _update_node_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_CODE,
        stage=STAGE_CODE,
        status=APPROVED,
    )
    _log_and_finish(con, "approve", node_id)


def handle_edit(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
    new_definition: str = "",
    new_name: str = "",
) -> None:
    """Edit a code: update definition and/or name, reset to draft, invalidate cache."""
    node_id = code["id"]
    old_def = code.get("definition", "")
    old_name = code.get("name", "")

    if not new_definition.strip() and not new_name.strip():
        logger.warning("Edit aborted: both definition and name are empty")
        return

    if new_definition == old_def and (not new_name.strip() or new_name == old_name):
        logger.info("Edit aborted: definition and name unchanged")
        return

    old_value: dict[str, Any] = {}
    new_value: dict[str, Any] = {}

    if new_definition.strip() and new_definition != old_def:
        _update_node_definition(con, node_id, new_definition, db_path=db_path)
        set_status_draft(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_CODE,
            stage=STAGE_CODE,
        )
        invalidate_code_embedding(con, node_id, code.get("tag", ""))
        old_value["definition"] = old_def
        new_value["definition"] = new_definition

    if new_name.strip() and new_name != old_name:
        _update_node_name(con, node_id, new_name, db_path=db_path)
        old_value["name"] = old_name
        new_value["name"] = new_name

    _log_and_finish(con, "edit", node_id, old_value, new_value)


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
    _log_and_finish(con, "reject", node_id)


def handle_defer(
    con: duckdb.DuckDBPyConnection,
    code: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Defer a code: log action only, no status change."""
    _log_and_finish(con, "defer", code["id"])
