"""Dirty flag propagation and checking for incremental recomputation.

Provides functions to set, propagate, clear, and check dirty flags.
Propagation walks the ontology DAG upward: marking a tag dirty also
marks all its ancestors dirty (so interpretation nodes spanning the
broader subtree detect staleness).

References:
    ADR-007 (Incremental Ontology Evolution): dirty-state propagation
"""

from typing import Dict

import duckdb
from persistence.state_updates import update_dirty_flag
from utils.logging import get_logger

logger = get_logger(__name__)


def set_dirty(con: duckdb.DuckDBPyConnection, tag: str) -> None:
    """Set the dirty flag for a single tag without upward propagation.

    Useful for fine-grained control.  Most callers should use
    :func:`propagate_dirty` instead so that ancestor tags are also
    marked dirty.

    Args:
        con: Active DuckDB connection.
        tag: Ontology tag string.

    Raises:
        StateError: If *tag* is not a string or persistence fails.
    """
    update_dirty_flag(con, tag, dirty=True)
    logger.debug("Dirty flag set", extra={"tag": tag})


def propagate_dirty(con: duckdb.DuckDBPyConnection, tag: str) -> None:
    """Mark *tag* and all its ontology ancestors as dirty.

    When a code/theme under *tag* is edited, code and theme inference
    for *tag* must rerun, AND interpretation synthesis for any broader
    tag that contains *tag* in its subtree must also rerun.

    This function:
    1. Sets ``dirty_flags[tag] = True``
    2. Walks the ontology DAG upward via :func:`get_ancestors`
    3. Sets ``dirty_flags[ancestor] = True`` for each ancestor

    Args:
        con: Active DuckDB connection.
        tag: Ontology tag string (e.g. ``"Problem.Cause"``).

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
        StateError: If persistence fails.
    """
    from ontology.traversal import get_ancestors

    affected = [tag]
    try:
        affected.extend(get_ancestors(tag))
    except (KeyError, Exception) as exc:
        logger.warning(
            "Could not resolve ontology ancestors for tag; " "setting bare dirty flag",
            extra={"tag": tag, "error": str(exc)},
        )
        update_dirty_flag(con, tag, dirty=True)
        return

    for t in affected:
        update_dirty_flag(con, t, dirty=True)

    logger.debug(
        "Dirty flags propagated upward",
        extra={"tag": tag, "affected": affected},
    )


def clear_dirty(con: duckdb.DuckDBPyConnection, tag: str) -> None:
    """Clear the dirty flag for *tag* (does not affect ancestors).

    Call after a tag's branch has been fully recomputed.

    Args:
        con: Active DuckDB connection.
        tag: Ontology tag string.

    Raises:
        StateError: If persistence fails.
    """
    update_dirty_flag(con, tag, dirty=False)
    logger.debug("Dirty flag cleared", extra={"tag": tag})


def clear_all_dirty(con: duckdb.DuckDBPyConnection) -> None:
    """Clear all dirty flags at once.

    Useful after a full pipeline run or stage completion.
    """
    from persistence.state_repository import load_state, save_state

    state = load_state(con)
    state["dirty_flags"] = {}
    save_state(con, state)
    logger.debug("All dirty flags cleared")


def is_dirty(tag: str, dirty_flags: Dict[str, bool]) -> bool:
    """Check whether *tag* is marked dirty in a dirty_flags dict.

    Pure function — no database access.  Suitable for use inside
    Hamilton node functions where the dirty_flags dict is passed as
    an external input.

    Args:
        tag: Ontology tag string.
        dirty_flags: Dict mapping tag → bool (e.g. from
            :func:`get_dirty_flags` or a Hamilton input).

    Returns:
        True if *tag* is explicitly set to True in *dirty_flags*.
    """
    return dirty_flags.get(tag, False)


def any_tag_dirty(tags: list[str], dirty_flags: Dict[str, bool]) -> bool:
    """Check whether *any* tag in a list is marked dirty.

    Pure function.  Useful for interpretation nodes: if any tag in
    a span is dirty, the whole span should be recomputed.

    Args:
        tags: List of ontology tag strings.
        dirty_flags: Dict mapping tag → bool.

    Returns:
        True if at least one tag in *tags* has a True dirty flag.
    """
    return any(dirty_flags.get(t, False) for t in tags)
