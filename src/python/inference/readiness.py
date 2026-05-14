"""Readiness tracking for interpretation synthesis.

A tag is "interpretation-ready" when ALL themes across its entire
subtree (tag + descendants via ``get_subtree``) are approved — no
draft or rejected themes remain anywhere in the subtree.  Ready tags
accumulate in ``session_state['interpretation_ready_tags']``, which
drives Feature 47 (interpretation synthesis).

Public functions
----------------
- ``check_tag_ready(con, tag, db_path=None) -> bool``
- ``remove_tag_from_ready(con, tag) -> None``
- ``get_ready_tags(con) -> list[str]``
- ``is_tag_in_ready_list(con, tag) -> bool``
"""

from typing import List, Set

import duckdb
from ontology import get_ancestors, get_subtree
from persistence.state_repository import load_state, save_state
from persistence.state_updates import update_dirty_flag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "check_tag_ready",
    "get_ready_tags",
    "is_tag_in_ready_list",
    "remove_tag_from_ready",
]


# ── Private helpers ────────────────────────────────────────────────────────


def _get_theme_statuses_for_tag(con: duckdb.DuckDBPyConnection, tag: str) -> List[str]:
    """Return distinct node statuses for all themes under *tag*.

    Returns an empty list when no themes exist for the tag.
    """
    rows = con.execute(
        "SELECT DISTINCT status FROM nodes " "WHERE type = 'theme' AND tag = ?",
        [tag],
    ).fetchall()
    return [r[0] for r in rows]


def _subtree_is_fully_approved(
    con: duckdb.DuckDBPyConnection,
    subtree_tags: Set[str],
) -> bool:
    """Check that every tag in *subtree_tags* has no draft or rejected themes.

    A tag with zero themes is vacuously OK (no themes to block).
    Returns ``True`` when all tags in the subtree are fully approved.
    """
    for st in sorted(subtree_tags):
        statuses = _get_theme_statuses_for_tag(con, st)
        if not statuses:
            continue
        if any(s in ("draft", "rejected") for s in statuses):
            return False
    return True


def _add_to_ready_tags(
    con: duckdb.DuckDBPyConnection,
    tags_to_add: Set[str],
) -> None:
    """Add *tags_to_add* to ``interpretation_ready_tags`` in session state.

    Preserves any existing entries and de-duplicates.
    """
    state = load_state(con)
    ready: List[str] = state.get("interpretation_ready_tags", [])
    existing: Set[str] = set(ready)
    for t in sorted(tags_to_add):
        if t not in existing:
            ready.append(t)
            existing.add(t)
    state["interpretation_ready_tags"] = ready
    save_state(con, state)
    logger.debug(
        "Tags added to interpretation_ready_tags",
        extra={"tags": sorted(tags_to_add)},
    )


def _remove_from_ready_tags(
    con: duckdb.DuckDBPyConnection,
    tags_to_remove: Set[str],
) -> None:
    """Remove *tags_to_remove* from ``interpretation_ready_tags``.

    Idempotent — safe to call when a tag is not in the list.
    """
    state = load_state(con)
    ready: List[str] = state.get("interpretation_ready_tags", [])
    remove_set: Set[str] = set(tags_to_remove)
    state["interpretation_ready_tags"] = [t for t in ready if t not in remove_set]
    save_state(con, state)
    logger.debug(
        "Tags removed from interpretation_ready_tags",
        extra={"tags": sorted(tags_to_remove)},
    )


# ── Public API ─────────────────────────────────────────────────────────────


def check_tag_ready(
    con: duckdb.DuckDBPyConnection,
    tag: str,
    db_path=None,
) -> bool:
    """Check if *tag*'s entire subtree is ready for interpretation synthesis.

    Queries the ontology DAG for all descendant tags via
    ``ontology.get_subtree(tag)``, then checks theme statuses for
    every tag in that set.

    1. If any tag in the subtree has draft or rejected themes → tag is
       **not** ready.  Removes *tag* + ancestors from the ready list
       and returns ``False``.
    2. Otherwise → tag is ready.  Adds *tag* + ancestors to
       ``interpretation_ready_tags``, sets ``dirty_flags[tag] = True``,
       and returns ``True``.

    Args:
        con: Active DuckDB connection.
        tag: Ontology tag to check (e.g. ``"Problem.Cause"``).
        db_path: DuckDB path (passed to ontology traversal).

    Returns:
        ``True`` when the tag subtree is fully interpretation-ready.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    subtree = get_subtree(tag)

    if not _subtree_is_fully_approved(con, subtree):
        remove_tag_from_ready(con, tag)
        return False

    ancestors = get_ancestors(tag)
    tags_to_add: Set[str] = {tag} | set(ancestors)
    _add_to_ready_tags(con, tags_to_add)
    update_dirty_flag(con, tag, True)

    logger.info(
        "Tag subtree is interpretation-ready",
        extra={
            "tag": tag,
            "subtree_tags": sorted(subtree),
            "ancestors": ancestors,
        },
    )
    return True


def remove_tag_from_ready(
    con: duckdb.DuckDBPyConnection,
    tag: str,
) -> None:
    """Remove *tag* and its ancestors from ``interpretation_ready_tags``.

    Called when a theme is edited or rejected, breaking readiness for
    the tag and any ancestor that depends on it.

    Args:
        con: Active DuckDB connection.
        tag: Ontology tag whose readiness is invalidated.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    ancestors = get_ancestors(tag)
    tags_to_remove: Set[str] = {tag} | set(ancestors)
    _remove_from_ready_tags(con, tags_to_remove)

    logger.info(
        "Tag and ancestors removed from ready list",
        extra={"tag": tag, "removed": sorted(tags_to_remove)},
    )


def get_ready_tags(
    con: duckdb.DuckDBPyConnection,
) -> List[str]:
    """Return the current ``interpretation_ready_tags`` list.

    Returns an empty list when no tags have been marked ready yet.
    """
    state = load_state(con)
    return list(state.get("interpretation_ready_tags", []))


def is_tag_in_ready_list(
    con: duckdb.DuckDBPyConnection,
    tag: str,
) -> bool:
    """Return ``True`` if *tag* is currently in the interpretation ready list."""
    ready = get_ready_tags(con)
    return tag in ready
