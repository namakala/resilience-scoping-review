"""Downstream invalidation for code merge operations.

``invalidate_themes`` marks themes containing merged codes as ``draft``.
``invalidate_interpretations`` marks interpretations spanning those themes
as ``draft``.  Both update ``inference_status`` when applicable.
"""

from inference.inference_status_crud import set_status_draft
from inference.inference_status_types import ENTITY_THEME, STAGE_THEME
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["invalidate_themes", "invalidate_interpretations"]


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
