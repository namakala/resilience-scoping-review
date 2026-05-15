"""Node: artifact loading — exemplars, tags, keywords, tag DAG.

All functions are pure.  Loading delegates to ``persistence.loaders``
(file-cache-backed, deterministic).
"""

from __future__ import annotations

import networkx as nx
import polars as pl
from pipeline.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "load_exemplars",
    "load_tags",
    "load_keywords",
    "extract_keywords",
    "resolve_tag_dag",
    "validate_artifact_schemas",
    "compute_exemplar_statistics",
    "prepare_artifact_summary",
]


def load_exemplars(config: Config) -> pl.LazyFrame:
    """Load exemplars from Parquet via persistence loader."""
    from persistence.loaders import load_exemplars as _load

    return _load()


def load_tags(config: Config) -> pl.LazyFrame:
    """Load tag ontology from Parquet via persistence loader."""
    from persistence.loaders import load_tags as _load

    return _load()


def extract_keywords(config: Config) -> dict:
    """Extract keywords from exemplars if not yet generated.

    Delegates to ``semantic.keyword_extraction.extract_keywords()`` which
    checks for existing ``keywords.parquet`` (idempotent — skips if exists),
    runs KeyBERT extraction if needed, and writes the file.

    Returns a status dict with row count for DAG output and downstream
    dependency wiring.
    """
    from semantic.keyword_extraction import extract_keywords as _extract

    lf = _extract(force_rebuild=False)
    rows = lf.collect().height
    logger.info("Keyword extraction complete", extra={"rows": rows})
    return {"status": "completed", "rows": rows}


def load_keywords(
    config: Config,
    extract_keywords: dict | None = None,
) -> pl.LazyFrame:
    """Load extracted keywords from Parquet via persistence loader.

    Depends on ``extract_keywords`` to ensure ``keywords.parquet`` exists
    before loading.  The ``extract_keywords`` parameter is unused — it
    exists purely to create the Hamilton dependency edge.
    """
    from persistence.loaders import load_keywords as _load

    return _load()


def resolve_tag_dag(load_tags: pl.LazyFrame, config: Config) -> nx.DiGraph:
    """Build a NetworkX DAG from the tag ontology LazyFrame.

    Each tag becomes a node with its ``depth`` attribute.  Parent→child
    edges are inferred from the dot-delimited tag hierarchy.
    """
    G = nx.DiGraph()
    df = load_tags.select(["tag", "parent", "description", "depth"]).collect()

    for row in df.iter_rows(named=True):
        tag = str(row["tag"])
        depth = int(row["depth"])
        G.add_node(tag, depth=depth, description=str(row.get("description", "")))

    for row in df.iter_rows(named=True):
        tag = str(row["tag"])
        parent = str(row.get("parent", ""))
        if parent and parent != "" and parent in G:
            G.add_edge(parent, tag)

    logger.info(
        "Tag DAG built",
        extra={"nodes": G.number_of_nodes(), "edges": G.number_of_edges()},
    )
    return G


def validate_artifact_schemas(
    load_exemplars: pl.LazyFrame,
    load_tags: pl.LazyFrame,
    load_keywords: pl.LazyFrame,
    config: Config,
) -> dict:
    """Validate required columns and types for all artifact LazyFrames."""
    expected = {
        "exemplars": {"id", "document", "tag", "content", "keywords"},
        "tags": {"tag", "parent", "description"},
        "keywords": {"keyword_id", "exemplar_id", "keyword_text"},
    }
    results = {}
    for name, lf in [
        ("exemplars", load_exemplars),
        ("tags", load_tags),
        ("keywords", load_keywords),
    ]:
        cols = set(lf.collect_schema().names())
        missing = expected[name] - cols
        results[name] = {"valid": len(missing) == 0, "missing_cols": list(missing)}
    return results


def compute_exemplar_statistics(load_exemplars: pl.LazyFrame, config: Config) -> dict:
    """Count exemplars, tag distribution, and keyword coverage."""
    df = load_exemplars.collect()
    total = df.height
    tag_dist = df.group_by("tag").agg(pl.len().alias("count")).to_dict(as_series=False)
    return {
        "total_exemplars": total,
        "tag_distribution": dict(zip(tag_dist["tag"], tag_dist["count"])),
    }


def prepare_artifact_summary(
    load_exemplars: pl.LazyFrame,
    load_tags: pl.LazyFrame,
    load_keywords: pl.LazyFrame,
    config: Config,
) -> dict:
    """Merged metadata dict for downstream use."""
    return {
        "exemplar_count": load_exemplars.collect().height,
        "tag_count": load_tags.collect().height,
        "keyword_count": load_keywords.collect().height,
    }
