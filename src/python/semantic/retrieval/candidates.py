"""Candidate ID resolution from in-memory scope maps.

Pure functions — no DuckDB queries.  Callers pass pre-computed scope and
entity maps that were built by the orchestration layer from the ontology
traversal cache and/or graph database.
"""

from __future__ import annotations

from typing import Callable

import polars as pl
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["resolve_candidate_ids"]


def resolve_candidate_ids(
    candidate_type: str,
    tag_scope_map: dict[str, set[int]],
    tag_entity_map: dict[int, str],
    tag_scope_fn: Callable[[str], set[str]] | None = None,
    load_exemplars_fn: Callable[[], pl.LazyFrame] | None = None,
) -> tuple[set[int], dict[int, str]]:
    """Resolve entity IDs for a candidate type from in-memory maps.

    For *exemplar* types the candidate pool comes from ``tag_entity_map``
    (pre-filtered by the caller).  For other types (code, theme,
    interpretation) the pool comes from ``tag_scope_map``.

    Parameters
    ----------
    candidate_type :
        ``'exemplar'``, ``'code'``, ``'theme'``, or ``'interpretation'``.
    tag_scope_map :
        Tag → set of entity IDs for non-exemplar types.  Ignored for
        exemplars.
    tag_entity_map :
        Entity ID → tag string for all candidates in scope.
    tag_scope_fn :
        **Deprecated** — kept for backward compat with orchestration
        callers that haven't migrated yet.
    load_exemplars_fn :
        **Deprecated** — kept for backward compat.

    Returns
    -------
    tuple[set[int], dict[int, str]]
        ``(candidate_ids, entity_id_to_tag_map)``.
    """
    if candidate_type == "exemplar":
        candidate_ids = set(tag_entity_map.keys())
    else:
        candidate_ids = set()
        for ids in tag_scope_map.values():
            candidate_ids.update(ids)

    return candidate_ids, tag_entity_map
