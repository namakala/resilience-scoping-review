"""Cache invalidation with descendant propagation and audit logging.

Extends Feature 19's basic stale-flag setting with:
- Cascade invalidation to all descendant tags
- Bulk invalidation in a single transaction
- Audit log recording (tag, reason, timestamp)

All public functions accept an optional ``reason`` string recorded in the
audit log. The default is ``"manual"`` for single-tag and ``"bulk"`` for
multi-tag invalidation.
"""

from pathlib import Path
from typing import List, Optional

from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .traversal import get_descendants

logger = get_logger(__name__)


def invalidate_cache_for_tag(
    tag: str,
    db_path: Optional[Path] = None,
    reason: str = "manual",
) -> None:
    """Mark *tag* and all its descendants as stale, and log the invalidation.

    On the next call to ``get_cached_subtree()`` for any affected tag, the
    stale row triggers recomputation.

    Args:
        tag: Ontology tag string.
        db_path: DuckDB path. Defaults to session DB.
        reason: Human-readable reason for invalidation.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    descendants = list(get_descendants(tag))
    tags = [tag] + descendants
    _invalidate_tags(tags, reason, db_path)


def invalidate_cache_for_tags(
    tags: List[str],
    db_path: Optional[Path] = None,
    reason: str = "bulk",
) -> None:
    """Mark multiple tags and their descendants as stale in a single transaction.

    Duplicate tags and overlapping descendant sets are deduplicated before
    execution. All updates and audit entries are committed atomically.

    Args:
        tags: List of ontology tag strings.
        db_path: DuckDB path. Defaults to session DB.
        reason: Human-readable reason for invalidation.

    Raises:
        KeyError: If any tag is not in the ontology DAG.
    """
    all_tags: set = set()
    for tag in tags:
        all_tags.add(tag)
        all_tags.update(get_descendants(tag))
    _invalidate_tags(list(all_tags), reason, db_path)


def _invalidate_tags(
    tags: List[str],
    reason: str,
    db_path: Optional[Path],
) -> None:
    """Set stale=TRUE for given tags and log audit entries in one transaction."""
    con = get_connection(db_path)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            for tag in tags:
                con.execute(
                    "UPDATE traversal_cache SET stale = TRUE WHERE tag = ?",
                    [tag],
                )
                _log_invalidation(con, tag, reason)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        logger.info(
            "Cache invalidated",
            extra={"tags": tags, "reason": reason, "count": len(tags)},
        )
    finally:
        con.close()


def _log_invalidation(con, tag: str, reason: str) -> None:
    """Insert an invalidation event into the audit log."""
    con.execute(
        "INSERT INTO invalidation_log (tag, reason) VALUES (?, ?)",
        [tag, reason],
    )
