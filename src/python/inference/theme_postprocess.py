"""Post-processing validators for theme inference results.

Provides pure-function validators: deduplicate theme names, flag
themes with fewer than 2 codes, and validate code-ID belonging.

Usage:
    from inference.theme_postprocess import dedup_theme_names, flag_small_themes

    themes = dedup_theme_names(themes)
    themes = flag_small_themes(themes)
    validate_code_belonging(themes, batch_code_ids, batch_id)
"""

from __future__ import annotations

from utils.logging import get_logger

from .parsing import ThemeInference

logger = get_logger(__name__)

__all__ = ["dedup_theme_names", "flag_small_themes", "validate_code_belonging"]


def dedup_theme_names(themes: list[ThemeInference]) -> list[ThemeInference]:
    """Deduplicate theme names by appending ``_1``, ``_2`` on collision.

    Logs a warning on each rename.  Mutates ``theme.theme_name`` in
    place and returns the same list for convenience.
    """
    seen: set[str] = set()
    for theme in themes:
        name = theme.theme_name
        if name in seen:
            counter = 1
            while f"{name}_{counter}" in seen:
                counter += 1
            theme.theme_name = f"{name}_{counter}"
            logger.warning(
                "Duplicate theme name resolved: '%s' -> '%s'",
                name,
                theme.theme_name,
            )
        seen.add(theme.theme_name)
    return themes


def flag_small_themes(themes: list[ThemeInference]) -> list[ThemeInference]:
    """Log a warning for any theme with fewer than 2 codes.

    Returns the same list (warnings fire as a side effect).
    """
    for theme in themes:
        if len(theme.code_ids) < 2:
            logger.warning(
                "Theme '%s' has %d code(s); flagged for review",
                theme.theme_name,
                len(theme.code_ids),
            )
    return themes


def validate_code_belonging(
    themes: list[ThemeInference],
    batch_code_ids: set[str],
    batch_id: str,
) -> None:
    """Verify every ``code_id`` in every theme belongs to *batch_code_ids*.

    Logs a warning for any code_id that falls outside the batch's
    approved code set (pre-flight: all codes in a theme must share
    the same parent tag, guaranteed by batch grouping).
    """
    for theme in themes:
        for cid in theme.code_ids:
            if cid not in batch_code_ids:
                logger.warning(
                    "Theme '%s' references code %s not in batch %s",
                    theme.theme_name,
                    cid,
                    batch_id,
                )
