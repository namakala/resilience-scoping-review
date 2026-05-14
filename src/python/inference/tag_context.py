"""Tag metadata fetching for inference prompt context.

Provides :func:`get_tag_metadata` to retrieve a tag's description and
ontology path (ancestors + self) from the loaded tag ontology. Used
by all inference services (code, theme, interpretation) to build
prompt context.

Usage:
    from inference.tag_context import get_tag_metadata

    description, ontology_path = get_tag_metadata("Problem.Cause")
"""

import polars as pl
from ontology import get_ancestors
from persistence.loaders import load_tags
from utils.logging import get_logger

logger = get_logger(__name__)


def get_tag_metadata(tag: str) -> tuple[str, list[str]]:
    """Return ``(description, ontology_path)`` for a tag.

    *description* is the tag's description string from the ontology.
    *ontology_path* is the ordered list of ancestors plus the tag itself,
    from root to tag (e.g. ``["root", "parent", "tag"]``).

    Args:
        tag: Ontology tag string (e.g. ``"Problem.Cause"``).

    Returns:
        Tuple of (description, ontology_path).

    Raises:
        KeyError: If *tag* is not found in the loaded ontology.
    """
    tags_lf = load_tags()
    row = tags_lf.filter(pl.col("tag") == tag).select(["description"]).collect()
    if row.is_empty():
        raise KeyError(f"Tag not found in ontology: {tag}")
    description = row["description"][0]
    ancestors = get_ancestors(tag)
    return description, ancestors + [tag]
