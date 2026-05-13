"""DuckDB-backed traversal cache for tag ontology.

Precomputes and persists ancestors, descendants, and subtree aggregates
for every tag. Builds on Feature 18's traversal API for computation, then
stores results as JSON arrays in the DuckDB traversal_cache table.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import polars as pl
from persistence.duckdb_connection import get_connection
from persistence.loaders import load_exemplars
from utils.logging import get_logger

from .cache_io import (
    compute_subtree_exemplar_ids,
    read_cache_row,
    resolve_tag,
    upsert_cache_row,
)
from .traversal import get_ancestors, get_descendants, get_subtree

logger = get_logger(__name__)


def _recompute_and_cache(
    con,
    tag: str,
    exemplars_df: pl.DataFrame,
    tag_col: pl.Expr,
) -> Dict[str, Any]:
    """Compute traversal, upsert to DuckDB, and return result dict."""
    ancestors = get_ancestors(tag)
    descendants = get_descendants(tag)
    subtree = get_subtree(tag)
    subtree_exemplar_ids = compute_subtree_exemplar_ids(
        exemplars_df,
        tag_col,
        subtree,
    )
    upsert_cache_row(
        con,
        tag=tag,
        ancestors=ancestors,
        descendants=descendants,
        subtree_exemplars=subtree_exemplar_ids,
        subtree_codes=[],
        subtree_themes=[],
    )
    return {
        "tag": tag,
        "ancestors": ancestors,
        "descendants": descendants,
        "subtree_exemplars": subtree_exemplar_ids,
        "subtree_codes": [],
        "subtree_themes": [],
    }


def build_traversal_cache(db_path: Optional[Path] = None) -> int:
    """Precompute traversal results for every tag in the ontology DAG.

    Iterates all tags, delegates to Feature 18 for traversal computation,
    and persists results in DuckDB as JSON arrays.

    Args:
        db_path: DuckDB path. Defaults to session DB.

    Returns:
        Number of tags cached.

    Raises:
        KeyError: If a DAG tag raises KeyError (should not happen).
    """
    from .dag import get_tag_dag

    G = get_tag_dag()
    tags = list(G.nodes())

    if not tags:
        logger.info("No tags to cache (empty DAG)")
        return 0

    con = get_connection(db_path)
    try:
        exemplars_df = load_exemplars().collect()
        tag_col = pl.col("tag").cast(pl.String)

        for tag in tags:
            _recompute_and_cache(con, tag, exemplars_df, tag_col)

        logger.info(
            "Traversal cache built",
            extra={"tags_cached": len(tags)},
        )
        return len(tags)
    finally:
        con.close()


def get_cached_subtree(
    tag: str,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Read cached traversal data for *tag* from DuckDB.

    If the row is missing or stale (stale=TRUE), recomputes using
    Feature 18 functions and updates the cache before returning.

    Args:
        tag: Ontology tag string.
        db_path: DuckDB path. Defaults to session DB.

    Returns:
        Dict with keys: tag, ancestors, descendants, subtree_exemplars,
        subtree_codes, subtree_themes.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    con = get_connection(db_path)
    try:
        row = read_cache_row(con, tag)

        if row is not None and not row["stale"]:
            return {
                "tag": row["tag"],
                "ancestors": row["ancestors"],
                "descendants": row["descendants"],
                "subtree_exemplars": row["subtree_exemplars"],
                "subtree_codes": row["subtree_codes"],
                "subtree_themes": row["subtree_themes"],
            }

        if row is None:
            logger.info("Cache miss, recomputing", extra={"tag": tag})
        else:
            logger.info("Cache stale, recomputing", extra={"tag": tag})

        resolve_tag(tag)
        exemplars_df = load_exemplars().collect()
        tag_col = pl.col("tag").cast(pl.String)
        return _recompute_and_cache(con, tag, exemplars_df, tag_col)
    finally:
        con.close()


def invalidate_cache_for_tag(
    tag: str,
    db_path: Optional[Path] = None,
) -> None:
    """Mark the cache row for *tag* as stale, triggering recompute on next read.

    Args:
        tag: Ontology tag string.
        db_path: DuckDB path. Defaults to session DB.
    """
    con = get_connection(db_path)
    try:
        con.execute(
            "UPDATE traversal_cache SET stale = TRUE WHERE tag = ?",
            [tag],
        )
        logger.info("Cache invalidated", extra={"tag": tag})
    finally:
        con.close()


def clear_duckdb_cache(db_path: Optional[Path] = None) -> None:
    """Delete all rows from the traversal_cache table.

    Args:
        db_path: DuckDB path. Defaults to session DB.
    """
    con = get_connection(db_path)
    try:
        con.execute("DELETE FROM traversal_cache")
        logger.info("Traversal cache cleared")
    finally:
        con.close()
