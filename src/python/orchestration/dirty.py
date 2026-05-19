"""Dirty flag propagation for incremental recomputation.

Propagation walks the ontology DAG upward: marking a tag dirty also
marks all its ancestors dirty so interpretation nodes spanning the
broader subtree detect staleness.
"""

import duckdb
from persistence.state_updates import update_dirty_flag
from utils.logging import get_logger

logger = get_logger(__name__)


def set_dirty(con: duckdb.DuckDBPyConnection, tag: str) -> None:
    """Set the dirty flag for a single tag without upward propagation."""
    update_dirty_flag(con, tag, dirty=True)
    logger.debug("Dirty flag set", extra={"tag": tag})


def propagate_dirty(con: duckdb.DuckDBPyConnection, tag: str) -> None:
    """Mark *tag* and all its ontology ancestors as dirty."""
    from ontology.traversal import get_ancestors

    affected = [tag]
    try:
        affected.extend(get_ancestors(tag))
    except (KeyError, Exception) as exc:
        logger.warning(
            "Could not resolve ontology ancestors for tag; setting bare dirty flag",
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
    """Clear the dirty flag for *tag* (does not affect ancestors)."""
    update_dirty_flag(con, tag, dirty=False)
    logger.debug("Dirty flag cleared", extra={"tag": tag})


def clear_all_dirty(con: duckdb.DuckDBPyConnection) -> None:
    """Clear all dirty flags at once."""
    from persistence.state_repository import load_state, save_state

    state = load_state(con)
    state["dirty_flags"] = {}
    save_state(con, state)
    logger.debug("All dirty flags cleared")
