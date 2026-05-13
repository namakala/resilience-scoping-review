"""Candidate ID resolution from ontology scope.

For exemplars, uses the traversal cache (``get_cached_subtree``).
For codes/themes/interpretations, queries the DuckDB nodes table
filtered by scope tags from ``get_scope_for_tag``.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

import duckdb
from ontology.cache import get_cached_subtree
from ontology.scope import get_scope_for_tag
from persistence.loaders import load_exemplars
from utils.logging import get_logger

logger = get_logger(__name__)


def resolve_candidate_ids(
    query_tag: str,
    candidate_type: str,
    con: duckdb.DuckDBPyConnection,
) -> Tuple[Set[int], Dict[int, str]]:
    """Resolve entity IDs in ``query_tag`` subtree for the given type.

    For exemplars, reads ``subtree_exemplars`` from the DuckDB-backed
    traversal cache and loads exemplars to build the id-to-tag map.
    For other types, queries the ``nodes`` table via DuckDB with the
    full set of in-scope tags.

    Args:
        query_tag: Ontology tag whose subtree defines the pool.
        candidate_type: ``'exemplar'``, ``'code'``, ``'theme'``, or
            ``'interpretation'``.
        con: Active DuckDB connection.

    Returns:
        ``(candidate_ids, entity_id_to_tag_map)``.
    """
    if candidate_type == "exemplar":
        cached = get_cached_subtree(query_tag)
        candidate_ids: Set[int] = set(cached["subtree_exemplars"])

        exemplars_df = load_exemplars().collect()
        entity_tag_map: Dict[int, str] = {}
        for row in exemplars_df.iter_rows(named=True):
            eid = int(row["id"])
            if eid in candidate_ids:
                entity_tag_map[eid] = str(row["tag"])
        return candidate_ids, entity_tag_map

    scope_tags = get_scope_for_tag(query_tag)
    if not scope_tags:
        return set(), {}

    placeholders = ",".join(["?"] * len(scope_tags))
    rows = con.execute(
        f"SELECT id, tag FROM nodes " f"WHERE tag IN ({placeholders}) AND type = ?",
        [*scope_tags, candidate_type],
    ).fetchall()

    candidate_ids = set()
    entity_tag_map = {}
    for row in rows:
        eid = int(row[0])
        tag = str(row[1])
        candidate_ids.add(eid)
        entity_tag_map[eid] = tag
    return candidate_ids, entity_tag_map
