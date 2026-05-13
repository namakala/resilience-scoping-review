"""Low-level DuckDB I/O for the traversal_cache table.

Functions here are public within the ``ontology`` package. Sibling modules
(cache_builder, constraint validator, scope helper) may import them directly.
They are implementation details of the ``ontology`` package and should not
be imported from outside the package.
"""

import json
from typing import Any, Dict, List, Optional

import polars as pl


def resolve_tag(tag: str) -> None:
    """Raise KeyError if *tag* is not in the ontology DAG."""
    from .dag import get_tag_dag

    if tag not in get_tag_dag():
        raise KeyError(f"Unknown tag: {tag}")


def compute_subtree_exemplar_ids(
    exemplars_df: pl.DataFrame,
    tag_col: pl.Expr,
    subtree: set,
) -> List[int]:
    """Extract sorted list of exemplar IDs whose tag falls in *subtree*."""
    if exemplars_df.is_empty():
        return []

    ids = exemplars_df.filter(tag_col.is_in(subtree)).select("id").to_series().to_list()
    return sorted(ids)


def read_cache_row(
    con,
    tag: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a traversal_cache row from DuckDB, deserializing JSON columns.

    Args:
        con: Open DuckDB connection.
        tag: Ontology tag string.

    Returns:
        Dict with keys ``tag``, ``ancestors``, ``descendants``,
        ``subtree_exemplars``, ``subtree_codes``, ``subtree_themes``, ``stale``.
        ``None`` if no row exists.
    """
    row = con.execute(
        "SELECT tag, ancestors, descendants, subtree_exemplars, "
        "subtree_codes, subtree_themes, stale "
        "FROM traversal_cache WHERE tag = ?",
        [tag],
    ).fetchone()

    if row is None:
        return None

    return {
        "tag": row[0],
        "ancestors": json.loads(row[1]),
        "descendants": json.loads(row[2]),
        "subtree_exemplars": json.loads(row[3]),
        "subtree_codes": json.loads(row[4]),
        "subtree_themes": json.loads(row[5]),
        "stale": row[6],
    }


def upsert_cache_row(
    con,
    tag: str,
    ancestors: List[str],
    descendants: List[str],
    subtree_exemplars: List[int],
    subtree_codes: List[int],
    subtree_themes: List[int],
) -> None:
    """Insert or replace a row in ``traversal_cache`` with JSON-serialized arrays.

    Args:
        con: Open DuckDB connection.
        tag: Ontology tag string.
        ancestors: Sorted list of ancestor tags.
        descendants: Sorted list of descendant tags.
        subtree_exemplars: Exemplar IDs in the tag's subtree.
        subtree_codes: Code IDs in the tag's subtree (initially empty).
        subtree_themes: Theme IDs in the tag's subtree (initially empty).
    """
    con.execute(
        """
        INSERT OR REPLACE INTO traversal_cache
            (tag, ancestors, descendants, subtree_exemplars,
             subtree_codes, subtree_themes, stale)
        VALUES (?, ?, ?, ?, ?, ?, FALSE)
        """,
        [
            tag,
            json.dumps(ancestors),
            json.dumps(descendants),
            json.dumps(subtree_exemplars),
            json.dumps(subtree_codes),
            json.dumps(subtree_themes),
        ],
    )
