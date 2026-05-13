"""Ontology module: tag DAG construction, traversal, and constraint validation."""

from .dag import build_tag_dag, get_tag_dag, rebuild_tag_dag, validate_tag_dag

__all__ = [
    "build_tag_dag",
    "get_tag_dag",
    "rebuild_tag_dag",
    "validate_tag_dag",
]
