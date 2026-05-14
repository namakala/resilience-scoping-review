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
    _log_and_finish(
        con,
        "edit",
        node_id,
        old_value={"definition": old_def},
        new_value={"definition": new_definition},
    )


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
