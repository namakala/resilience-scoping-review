"""Name collision utilities for inference node creation.

Provides :func:`make_unique_name` for suffix-based dedup,
:func:`check_duplicate_names` for generic within-batch warnings,
and :func:`check_duplicate_theme_names` typed on ``ThemeInference``.

Usage:
    from inference.name_utils import make_unique_name, check_duplicate_names

    used = {"A", "B"}
    name = make_unique_name("A", used, entity_type="interpretation")
    # -> "A_1"

    check_duplicate_names(interps, lambda i: i.interpretation_name)
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Any, Callable

from utils.logging import get_logger

from .parsing import ThemeInference

logger = get_logger(__name__)

__all__ = [
    "check_duplicate_names",
    "check_duplicate_theme_names",
    "make_unique_name",
]


def make_unique_name(
    name: str,
    used_names: AbstractSet[str],
    entity_type: str = "item",
) -> str:
    """Resolve name collision by appending ``_1``, ``_2``, etc.

    If *name* is not in *used_names* it is returned unchanged.
    Otherwise a suffix is appended until a unique name is found.

    Args:
        name: Candidate name to make unique.
        used_names: Set of already-used names to check against.
        entity_type: Human-readable label for log messages
            (e.g. ``"theme"``, ``"interpretation"``).

    Returns:
        Unique name, possibly with ``_N`` suffix.
    """
    if name not in used_names:
        return name
    counter = 1
    while f"{name}_{counter}" in used_names:
        counter += 1
    logger.warning(
        "Duplicate %s name '%s' resolved to '%s_%d'",
        entity_type,
        name,
        name,
        counter,
    )
    return f"{name}_{counter}"


def check_duplicate_names(
    items: list[Any],
    get_name: Callable[[Any], str],
    entity_type: str = "item",
) -> None:
    """Log a warning for any duplicate names within *items*.

    Flags potential merge candidates. The actual deduplication is
    handled upstream by the post-processors for each entity type.

    Args:
        items: List of objects to check for duplicate names.
        get_name: Callable extracting the name from each item.
        entity_type: Human-readable label for log messages.
    """
    seen: dict[str, int] = {}
    for idx, item in enumerate(items):
        name = get_name(item)
        if name in seen:
            logger.warning(
                "Duplicate %s name '%s' (merge candidates: index %d and %d)",
                entity_type,
                name,
                seen[name],
                idx,
            )
        else:
            seen[name] = idx


def check_duplicate_theme_names(themes: list[ThemeInference]) -> None:
    """Log a warning for any duplicate theme names within *themes*.

    Delegates to :func:`check_duplicate_names` with ``entity_type="theme"``.
    """
    check_duplicate_names(themes, lambda t: t.theme_name, entity_type="theme")
