"""Embedding and status invalidation for HITL mutations.

Provides functions to invalidate embedding cache entries and mark
downstream entities as ``draft`` after edits, merges, and other
mutations that change entity content.

Grouped logically:
- Entity embedding invalidation (code, theme, interpretation)
- Downstream cascade invalidation (theme -> draft, interpretation -> draft)
"""

import duckdb
from inference.inference_status_crud import set_status_draft
from inference.inference_status_types import ENTITY_THEME, STAGE_THEME
from persistence.embedding_cache import invalidate_entity
from persistence.state_updates import update_dirty_flag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "invalidate_code_embedding",
    "invalidate_theme_embedding",
    "invalidate_interpretation_embedding",
    "invalidate_themes",
    "invalidate_interpretations",
]


# ── Entity embedding invalidation ───────────────────────────────────
# Called by action handlers after edits to reset embeddings for
# the changed entity and mark its ontology branch as dirty.


def invalidate_code_embedding(
    con: duckdb.DuckDBPyConnection,
    code_id: int,
    tag: str,
) -> None:
    """Invalidate a code's embedding cache and mark its tag branch as dirty.

    Args:
        con: Active DuckDB connection.
        code_id: ID of the code node.
        tag: Ontology tag associated with the code (e.g. ``"Problem.Cause"``).
    """
    invalidate_entity(con, str(code_id), "code")
    if tag:
        update_dirty_flag(con, tag)
    logger.debug(
        "Code embedding invalidated",
        extra={"code_id": code_id, "tag": tag},
    )


def invalidate_theme_embedding(
    con: duckdb.DuckDBPyConnection,
    theme_id: int,
    tag: str,
) -> None:
    """Invalidate a theme's embedding cache and mark its tag branch as dirty.

    Args:
        con: Active DuckDB connection.
        theme_id: ID of the theme node.
        tag: Ontology tag associated with the theme.
    """
    invalidate_entity(con, str(theme_id), "theme")
    if tag:
        update_dirty_flag(con, tag)
    logger.debug(
        "Theme embedding invalidated",
        extra={"theme_id": theme_id, "tag": tag},
    )


def invalidate_interpretation_embedding(
    con: duckdb.DuckDBPyConnection,
    interp_id: int,
    tag_spans: list[str],
) -> None:
    """Invalidate an interpretation's embedding and mark its tag branches dirty.

    Args:
        con: Active DuckDB connection.
        interp_id: ID of the interpretation node.
        tag_spans: List of ontology tags in the interpretation's span.
    """
    invalidate_entity(con, str(interp_id), "interpretation")
    for tag in tag_spans:
        if tag:
            update_dirty_flag(con, tag)
    logger.debug(
        "Interpretation embedding invalidated",
        extra={"interp_id": interp_id, "tag_spans": tag_spans},
    )


# ── Downstream cascade invalidation ─────────────────────────────────
# Called by merge handlers to mark affected themes and interpretations
# as draft so they are re-processed on the next pipeline run.


def invalidate_themes(con, source_id: int, target_id: int) -> list[int]:
    """Mark themes containing *source_id* or *target_id* as draft.

    Returns the list of affected theme IDs for cascade invalidation.
    """
    rows = con.execute(
        "SELECT DISTINCT source_id FROM edges "
        "WHERE target_id IN (?, ?) AND edge_type = 'composed-of'",
        [source_id, target_id],
    ).fetchall()
    theme_ids = [r[0] for r in rows]

    for theme_id in theme_ids:
        con.execute(
            "UPDATE nodes SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            [theme_id],
        )
        try:
            set_status_draft(con, str(theme_id), ENTITY_THEME, STAGE_THEME)
        except ValueError:
            logger.warning(
                "Could not set inference status to draft for theme",
                extra={"theme_id": theme_id},
            )

    if theme_ids:
        logger.info(
            "Themes invalidated to draft by merge",
            extra={"theme_ids": theme_ids},
        )

    return theme_ids


def invalidate_interpretations(con, theme_ids: list[int]) -> None:
    """Mark interpretations spanning any of *theme_ids* as draft."""
    if not theme_ids:
        return

    placeholders = ",".join("?" for _ in theme_ids)
    rows = con.execute(
        f"SELECT DISTINCT source_id FROM edges "
        f"WHERE target_id IN ({placeholders}) AND edge_type = 'spans'",
        theme_ids,
    ).fetchall()
    interp_ids = [r[0] for r in rows]

    for interp_id in interp_ids:
        con.execute(
            "UPDATE nodes SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            [interp_id],
        )

    if interp_ids:
        logger.info(
            "Interpretations invalidated to draft by merge",
            extra={"interp_ids": interp_ids},
        )
