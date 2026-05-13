"""Ontology module: tag DAG construction, traversal, and constraint validation."""

from .cache import (
    build_traversal_cache,
    clear_duckdb_cache,
    get_cached_subtree,
    invalidate_cache_for_tag,
)
from .dag import build_tag_dag, get_tag_dag, rebuild_tag_dag, validate_tag_dag
from .traversal import (
    clear_traversal_cache,
    get_ancestors,
    get_descendants,
    get_subtree,
    is_ancestor,
)

__all__ = [
    "build_tag_dag",
    "get_tag_dag",
    "rebuild_tag_dag",
    "validate_tag_dag",
    "get_ancestors",
    "get_descendants",
    "get_subtree",
    "is_ancestor",
    "clear_traversal_cache",
    "build_traversal_cache",
    "get_cached_subtree",
    "invalidate_cache_for_tag",
    "clear_duckdb_cache",
]
