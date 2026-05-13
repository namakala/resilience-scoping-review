"""Scope restriction helper: get_scope_for_tag returns tag + descendants set.

Used by the semantic retrieval layer (ADR-006, stage 1) to filter candidate
entities before BM25 and embedding ranking. Delegates to the DuckDB-backed
traversal cache (Feature 19) for O(1) cache-hit lookup with auto-recompute
on miss/stale.
"""

from pathlib import Path
from typing import Optional, Set

from utils.logging import get_logger

from .cache import get_cached_subtree

logger = get_logger(__name__)


def get_scope_for_tag(tag: str, db_path: Optional[Path] = None) -> Set[str]:
    """Return set of all tag IDs considered "in scope" for *tag*.

    Scope = {tag} U descendants(tag). For leaf tags, scope = {tag}.
    For root tags, scope = all tags in the ontology DAG.

    Args:
        tag: Ontology tag string.
        db_path: DuckDB path. Defaults to session DB.

    Returns:
        Set of tag strings representing the tag's full subtree.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    cached = get_cached_subtree(tag, db_path)
    return {cached["tag"]} | set(cached["descendants"])
