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
) -> None:
    """Approve the current entity."""
    if entity_type == "code":
        from hitl.code_review_actions import handle_approve

        handle_approve(con, entity, db_path=db_path)
    elif entity_type == "theme":
        from hitl.theme_review_actions import handle_approve_theme

        handle_approve_theme(con, entity, db_path=db_path)
    elif entity_type == "interpretation":
        from hitl.interpretation_review_actions import handle_approve_interpretation

        handle_approve_interpretation(con, entity, db_path=db_path)


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
    selected_ids: list[int],
    entity_type: str = "interpretation",
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Split an entity by regrouping its constituent items.

    Computes the second group automatically (remaining items),
    then dispatches to the type-specific split handler.

    For codes: splits exemplars into two groups, re-infers via LLM.
    For themes: splits codes into two groups, re-infers via LLM.
    For interpretations: splits themes into two groups, re-infers via LLM.
    """
    first_ids = selected_ids

    if entity_type == "code":
        from hitl.code_review_split import handle_split_code_regroup
        from hitl.queries_codes import get_code_exemplar_ids

        all_ids = get_code_exemplar_ids(con, entity["id"])
        second_ids = [eid for eid in all_ids if eid not in first_ids]
        if not first_ids or not second_ids:
            raise ValueError("Split requires at least one exemplar in each group")
        return handle_split_code_regroup(
            con=con,
            code=entity,
            first_exemplar_ids=first_ids,
            second_exemplar_ids=second_ids,
            db_path=db_path,
        )

    elif entity_type == "theme":
        from hitl.queries_themes import get_theme_code_ids
        from hitl.theme_review_split import handle_split_theme_regroup

        all_ids = get_theme_code_ids(con, entity["id"])
        second_ids = [cid for cid in all_ids if cid not in first_ids]
        if not first_ids or not second_ids:
            raise ValueError("Split requires at least one code in each group")
        return handle_split_theme_regroup(
            con=con,
            theme=entity,
            first_code_ids=first_ids,
            second_code_ids=second_ids,
            db_path=db_path,
        )

    elif entity_type == "interpretation":
        from hitl.interpretation_review_split import handle_split_interpretation_regroup
        from hitl.queries_interpretations import get_interpretation_themes

        all_themes = get_interpretation_themes(con, entity["id"])
        all_theme_ids = [t["id"] for t in all_themes]
        second_ids = [tid for tid in all_theme_ids if tid not in first_ids]
        if not first_ids or not second_ids:
            raise ValueError("Split requires at least one theme in each group")
        return handle_split_interpretation_regroup(
            con=con,
            interp=entity,
            first_theme_ids=first_ids,
            second_theme_ids=second_ids,
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
