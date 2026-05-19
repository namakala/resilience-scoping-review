"""Simple action handlers for theme review HITL CLI.

Provides ``handle_approve_theme``, ``handle_edit_theme``,
``handle_reject_theme``, and ``handle_defer_theme`` plus private
helpers for node updates.  (``handle_merge_themes`` lives in
``theme_review_merge.py``.)
"""

from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import create_edge, rebuild_graph
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import (
    APPROVED,
    ENTITY_THEME,
    REJECTED,
    STAGE_THEME,
)
from utils.logging import get_logger

from .invalidation import invalidate_theme_embedding
from .shared import (
    _log_and_finish,
    _update_node_data_json,
    _update_node_definition,
    _update_node_name,
    _update_node_status,
    console,
)

logger = get_logger(__name__)

__all__ = [
    "handle_approve_theme",
    "handle_edit_theme",
    "handle_reject_theme",
    "handle_defer_theme",
]


# ── Node update helper (unique to themes) ──────────────────────────


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
    """Approve a theme: validate constraints, set status and inference status."""
    node_id = theme["id"]

    from ontology import validate_constraint

    validate_constraint({"id": node_id, "type": "theme"}, "approve")

    _update_node_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
        status=APPROVED,
    )
    _log_and_finish(con, "approve", node_id)

    # Check if theme approval makes the entire tag subtree interpretation-ready
    from inference.readiness import check_tag_ready

    if check_tag_ready(con, theme["tag"], db_path=db_path):
        tag_label = theme["tag"]
        console.print(
            f"[bold green]✓ Tag '{tag_label}' is interpretation-ready! "
            f"All themes in subtree approved.[/bold green]"
        )


def handle_edit_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
    db_path: Optional[Path] = None,
    new_narrative: str = "",
    new_code_ids: Optional[list[int]] = None,
    new_name: str = "",
) -> None:
    """Edit a theme: update narrative, optionally codes, and/or name, reset to draft."""
    node_id = theme["id"]
    old_narrative = theme.get("narrative", "")
    old_name = theme.get("name", "")

    if not new_narrative.strip() and not new_name.strip():
        logger.warning("Edit aborted: both narrative and name are empty")
        return

    if (
        new_narrative == old_narrative
        and new_code_ids is None
        and (not new_name.strip() or new_name == old_name)
    ):
        logger.info(
            "Edit aborted: narrative unchanged, no code changes, and name unchanged"
        )
        return

    old_value: dict[str, Any] = {}
    new_value: dict[str, Any] = {}

    if new_narrative.strip() and new_narrative != old_narrative:
        old_data_json = theme.get("data_json") or {}
        _update_node_definition(con, node_id, new_narrative, db_path=db_path)
        old_value["narrative"] = old_narrative
        new_value["narrative"] = new_narrative

        if new_code_ids is not None:
            _update_theme_codes(con, node_id, new_code_ids, db_path=db_path)
            updated_data_json = {**old_data_json, "code_ids": new_code_ids}
            _update_node_data_json(con, node_id, updated_data_json, db_path=db_path)
    elif new_code_ids is not None:
        old_data_json = theme.get("data_json") or {}
        _update_theme_codes(con, node_id, new_code_ids, db_path=db_path)
        updated_data_json = {**old_data_json, "code_ids": new_code_ids}
        _update_node_data_json(con, node_id, updated_data_json, db_path=db_path)

    if new_name.strip() and new_name != old_name:
        _update_node_name(con, node_id, new_name, db_path=db_path)
        old_value["name"] = old_name
        new_value["name"] = new_name

    set_status_draft(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
    )
    invalidate_theme_embedding(con, node_id, theme.get("tag", ""))
    _log_and_finish(con, "edit", node_id, old_value, new_value)

    # Editing resets theme to draft → re-check subtree readiness
    from inference.readiness import check_tag_ready

    check_tag_ready(con, theme["tag"], db_path=db_path)


def handle_reject_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject a theme: set node status and inference status to rejected."""
    node_id = theme["id"]
    _update_node_status(con, node_id, "rejected", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_THEME,
        stage=STAGE_THEME,
        status=REJECTED,
    )
    _log_and_finish(con, "reject", node_id)

    # Rejecting a theme breaks subtree readiness → re-check
    from inference.readiness import check_tag_ready

    check_tag_ready(con, theme["tag"], db_path=db_path)


def handle_defer_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict[str, Any],
) -> None:
    """Defer a theme: log action only, no status change."""
    _log_and_finish(con, "defer", theme["id"])
