"""Action dispatch wrappers for TUI review actions.

Bridges Textual keybindings to existing hitl action handlers.
Each function validates the current entity and dispatches to
the handler for the matching entity_type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb


def action_approve(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
    entity_type: str,
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Approve the current entity.

    Returns:
        For interpretations: a dict ``{"approved": bool, "warning": str | None}``
        with a warning if tag_spans were non-contiguous.
        For codes and themes: ``None``.
    """
    if entity_type == "code":
        from hitl.code_review_actions import handle_approve

        handle_approve(con, entity, db_path=db_path)
        return None
    elif entity_type == "theme":
        from hitl.theme_review_actions import handle_approve_theme

        handle_approve_theme(con, entity, db_path=db_path)
        return None
    elif entity_type == "interpretation":
        from hitl.interpretation_review_actions import handle_approve_interpretation

        return handle_approve_interpretation(con, entity, db_path=db_path)
    raise ValueError(f"Unknown entity type: {entity_type}")


def action_reject(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
    entity_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Reject the current entity."""
    if entity_type == "code":
        from hitl.code_review_actions import handle_reject

        handle_reject(con, entity, db_path=db_path)
    elif entity_type == "theme":
        from hitl.theme_review_actions import handle_reject_theme

        handle_reject_theme(con, entity, db_path=db_path)
    elif entity_type == "interpretation":
        from hitl.interpretation_review_actions import handle_reject_interpretation

        handle_reject_interpretation(con, entity, db_path=db_path)


def action_edit(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
    entity_type: str,
    new_name: str,
    new_definition: str,
    db_path: Optional[Path] = None,
) -> None:
    """Edit the current entity with new name and/or definition."""
    if entity_type == "code":
        from hitl.code_review_actions import handle_edit

        handle_edit(
            con,
            entity,
            db_path=db_path,
            new_definition=new_definition,
            new_name=new_name,
        )
    elif entity_type == "theme":
        from hitl.theme_review_actions import handle_edit_theme

        handle_edit_theme(
            con,
            entity,
            db_path=db_path,
            new_narrative=new_definition,
            new_name=new_name,
        )
    elif entity_type == "interpretation":
        from hitl.interpretation_review_actions import handle_edit_interpretation

        handle_edit_interpretation(
            con,
            entity,
            db_path=db_path,
            new_narrative=new_definition,
            new_name=new_name,
        )


def action_merge(
    con: duckdb.DuckDBPyConnection,
    source_entity: dict[str, Any],
    target_id: int,
    entity_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Merge source into target."""
    if entity_type == "code":
        from hitl.code_review_merge import handle_merge

        handle_merge(con, source_entity, target_id, db_path=db_path)
    elif entity_type == "theme":
        from hitl.theme_review_merge import handle_merge_themes

        handle_merge_themes(con, source_entity, target_id, db_path=db_path)
    elif entity_type == "interpretation":
        from hitl.interpretation_review_merge import handle_merge_interpretations

        handle_merge_interpretations(con, source_entity, target_id, db_path=db_path)


def action_defer(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
    entity_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Defer the current entity."""
    if entity_type == "code":
        from hitl.code_review_actions import handle_defer

        handle_defer(con, entity, db_path=db_path)
    elif entity_type == "theme":
        from hitl.theme_review_actions import handle_defer_theme

        handle_defer_theme(con, entity)
    elif entity_type == "interpretation":
        from hitl.interpretation_review_actions import handle_defer_interpretation

        handle_defer_interpretation(con, entity)


def action_split(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
    all_groups: list[list[int]],
    entity_type: str = "interpretation",
    db_path: Optional[Path] = None,
) -> list[int]:
    """Split an entity by regrouping its constituent items.

    All groups are passed directly from the iterative split flow
    (no auto-compute of remaining items). Dispatches to the
    type-specific backend handler.

    For codes: splits exemplars into N groups, re-infers via LLM.
    For themes: splits codes into N groups, re-infers via LLM.
    For interpretations: splits themes into N groups, re-infers via LLM.
    """
    if len(all_groups) < 2:
        raise ValueError("Split requires at least 2 groups.")
    for i, g in enumerate(all_groups):
        if not g:
            raise ValueError(f"Group {i+1} must have at least one item.")

    if entity_type == "code":
        from hitl.code_review_split import handle_split_code_regroup

        return handle_split_code_regroup(
            con=con,
            code=entity,
            groups=all_groups,
            db_path=db_path,
        )

    elif entity_type == "theme":
        from hitl.theme_review_split import handle_split_theme_regroup

        return handle_split_theme_regroup(
            con=con,
            theme=entity,
            groups=all_groups,
            db_path=db_path,
        )

    elif entity_type == "interpretation":
        from hitl.interpretation_review_split import handle_split_interpretation_regroup

        return handle_split_interpretation_regroup(
            con=con,
            interp=entity,
            groups=all_groups,
            db_path=db_path,
        )

    else:
        raise ValueError(f"Split is not supported for entity type '{entity_type}'")


__all__ = [
    "action_approve",
    "action_reject",
    "action_edit",
    "action_merge",
    "action_split",
    "action_defer",
]
