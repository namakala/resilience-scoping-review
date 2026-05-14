"""Theme name collision utilities.

Provides :func:`make_unique_theme_name` for suffix-based dedup and
:func:`check_duplicate_theme_names` for within-batch duplicate warnings.

Usage:
    from inference.theme_name_utils import make_unique_theme_name

    used = {"A", "B"}
    name = make_unique_theme_name("A", used)  # -> "A_1"
"""

from __future__ import annotations

from utils.logging import get_logger

from .parsing import ThemeInference

logger = get_logger(__name__)

__all__ = ["check_duplicate_theme_names", "make_unique_theme_name"]


def make_unique_theme_name(name: str, used_names: set[str]) -> str:
    """Resolve name collision by appending ``_1``, ``_2``, etc.

    If *name* is not in *used_names* it is returned unchanged.
    Otherwise a suffix is appended until a unique name is found.
    """
    if name not in used_names:
        return name
    counter = 1
    while f"{name}_{counter}" in used_names:
        counter += 1
    logger.warning(
        "Duplicate theme name '%s' resolved to '%s_%d'",
        name,
        name,
        counter,
    )
    return f"{name}_{counter}"


def check_duplicate_theme_names(themes: list[ThemeInference]) -> None:
    """Log a warning for any duplicate theme names within *themes*.

    Flags potential merge candidates for the HITL review phase.
    The actual deduplication is handled upstream by
    :func:`~inference.theme_postprocess.dedup_theme_names`.
    """
    seen: dict[str, int] = {}
    for theme in themes:
        name = theme.theme_name
        if name in seen:
            logger.warning(
                "Duplicate theme name '%s' (merge candidates: " "index %d and %d)",
                name,
                seen[name],
                themes.index(theme),
            )
        else:
            seen[name] = themes.index(theme)
