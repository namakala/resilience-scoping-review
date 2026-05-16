"""Post-processing validators for theme inference results.

Provides pure-function validators: deduplicate theme names, flag
themes with fewer than 2 codes, auto-merge single-code themes into
multi-code themes, and validate code-ID belonging.

Usage:
    from inference.theme_postprocess import dedup_theme_names, flag_small_themes

    themes = dedup_theme_names(themes)
    themes = flag_small_themes(themes)
    themes = auto_merge_single_code_themes(themes, con)
    validate_code_belonging(themes, batch_code_ids, batch_id)
"""

from __future__ import annotations

import duckdb
from utils.logging import get_logger

from .parsing import ThemeInference

logger = get_logger(__name__)

__all__ = [
    "auto_merge_single_code_themes",
    "dedup_theme_names",
    "flag_small_themes",
    "validate_code_belonging",
]


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


def auto_merge_single_code_themes(
    themes: list[ThemeInference],
    con: duckdb.DuckDBPyConnection,
    db_path: str | None = None,
) -> list[ThemeInference]:
    """Merge single-code themes into multi-code themes within the same tag.

    For each theme with fewer than 2 codes, attempts to merge its code
    into another theme in the same tag (``theme.tag``).  If a merge
    target exists, the single code ID is appended to the target's
    ``code_ids`` list and the single-code theme is dropped from the
    result.  If no merge target exists (i.e. all themes for that tag
    are single-code), the theme is kept as-is with a warning.

    This function works purely on ``ThemeInference`` objects in memory.
    The *con* and *db_path* parameters are accepted for API consistency
    with other post-processors but are not used.

    Args:
        themes: List of ``ThemeInference`` objects to process.
        con: DuckDB connection (unused — in-memory only).
        db_path: Optional database path (unused).

    Returns:
        Modified list with single-code themes merged into targets.
    """
    # Group themes by tag
    by_tag: dict[str, list[ThemeInference]] = {}
    for theme in themes:
        by_tag.setdefault(theme.tag, []).append(theme)

    result: list[ThemeInference] = []

    for tag, tag_themes in by_tag.items():
        # Separate into multi-code (merge targets) and single-code (candidates)
        multi: list[ThemeInference] = []
        single: list[ThemeInference] = []
        for theme in tag_themes:
            if len(theme.code_ids) < 2:
                single.append(theme)
            else:
                multi.append(theme)

        if not multi:
            # No merge targets available — keep all single-code themes as-is
            for theme in single:
                logger.warning(
                    "Tag '%s': single-code theme '%s' has no merge target; "
                    "keeping as-is",
                    tag,
                    theme.theme_name,
                )
            result.extend(single)
            continue

        # Merge each single-code theme into the first multi-code target
        for src in single:
            target = multi[0]
            target.code_ids.extend(src.code_ids)
            logger.info(
                "Merged single-code theme '%s' (code_ids=%s) into '%s' " "for tag '%s'",
                src.theme_name,
                src.code_ids,
                target.theme_name,
                tag,
            )
            # src is intentionally NOT added to result — its codes are now in target

        result.extend(multi)

    return result


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
