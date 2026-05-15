"""HITL coordinator — pre-checks pending items, delegates to review, post-syncs state.

Sits between ``runner.run_pipeline()`` and the HITL review modules.
Provides auto-advance when no items need review and state reconciliation
after interactive sessions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
from orchestration.state import WorkflowState
from utils.logging import get_logger

logger = get_logger(__name__)


def coordinate_hitl(
    con: duckdb.DuckDBPyConnection,
    stage: int,
    state: WorkflowState,
    db_path: Optional[Path] = None,
) -> WorkflowState:
    """Coordinate HITL review for *stage*.

    Steps:
    1. Resolve artifact type from stage number (5→code, 7→theme, 9→interpretation).
    2. Query pending (draft) items of that type.
    3. If none, log and return state unchanged (runner auto-advances).
    4. Delegate to the existing interactive HITL review module.
    5. Reload state from DB to capture HITL-side mutations
       (user_action_count, dirty_flags).
    6. Return updated state.

    Args:
        con: Active DuckDB connection.
        stage: Pipeline stage number (5, 7, or 9).
        state: Current workflow state.
        db_path: Path to DuckDB file (needed by graph sync operations).

    Returns:
        Updated workflow state (possibly unchanged if no items to review).
    """
    artifact_type = _resolve_artifact_type(stage)
    if artifact_type is None:
        logger.warning("No HITL mapping for stage %d; skipping review", stage)
        return state

    pending = _query_pending(con, artifact_type)
    if not pending:
        logger.info("No pending %ss to review; auto-advancing", artifact_type)
        return state

    logger.info(
        "Stage %d — %d pending %s(s) to review",
        stage,
        len(pending),
        artifact_type,
    )

    _enter_review(con, artifact_type, db_path)

    # Post-HITL: reload state to capture HITL-side mutations
    # (user_action_count, dirty_flags, etc.)
    from persistence.state_repository import load_state

    updated_dict = load_state(con)
    return WorkflowState.from_state_dict(updated_dict)


# ── Private helpers ─────────────────────────────────────────────────────────


def _resolve_artifact_type(stage: int) -> Optional[str]:
    """Map a review stage number to its artifact type string.

    Returns ``None`` for non-review stages.
    """
    type_map = {5: "code", 7: "theme", 9: "interpretation"}
    return type_map.get(stage)


def _query_pending(con: duckdb.DuckDBPyConnection, artifact_type: str) -> list:
    """Fetch pending (draft) items of *artifact_type*.

    Dispatches to the appropriate HITL query module.
    Returns a (possibly empty) list.  The caller only checks truthiness,
    so item contents are not critical here.
    """
    if artifact_type == "code":
        from hitl.queries_codes import get_pending_codes

        return get_pending_codes(con)
    elif artifact_type == "theme":
        from hitl.queries_themes import get_pending_themes

        return get_pending_themes(con)
    elif artifact_type == "interpretation":
        from hitl.queries_interpretations import get_pending_interpretations

        return get_pending_interpretations(con)
    logger.warning("Unknown artifact type '%s'; no pending query", artifact_type)
    # Return an empty list for unknown types to avoid crashing downstream.
    # This is a safety valve — the coordinator should only be called
    # with valid artifact types.
    return []


def _enter_review(
    con: duckdb.DuckDBPyConnection,
    artifact_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Delegate to the existing HITL review dispatch."""
    from orchestration.review import enter_review
    from persistence.duckdb_connection import DEFAULT_DB_PATH

    enter_review(con, artifact_type, db_path or DEFAULT_DB_PATH)


__all__ = ["coordinate_hitl"]
