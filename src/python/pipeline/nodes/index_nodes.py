"""Nodes: BM25 index, ontology graph, traversal cache, scope index.

Pure functions that construct in-memory indices from artifact LazyFrames.
"""

from __future__ import annotations

import networkx as nx
import polars as pl
from pipeline.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "build_bm25",
    "build_ontology_graph",
    "materialize_traversal_cache",
    "validate_ontology_constraints",
    "build_tag_scope_index",
    "compute_ontology_statistics",
    "build_combined_index_metadata",
]


def build_bm25(load_keywords: pl.LazyFrame, config: Config) -> dict:
    """Build BM25 index from keyword data via pure index builder."""
    from semantic.index_builder import build_index as _build

    return _build(load_keywords, config.bm25_tokenizer_config)


def build_ontology_graph(load_tags: pl.LazyFrame, config: Config) -> nx.DiGraph:
    """Build a NetworkX ontology DAG from tag LazyFrame.

    Nodes have ``depth`` and ``description`` attributes.  Edges run from
    parent to child tags.
    """
    G = nx.DiGraph()
    df = load_tags.select(["tag", "parent", "description", "depth"]).collect()
    for row in df.iter_rows(named=True):
        tag = str(row["tag"])
        G.add_node(
            tag, depth=int(row["depth"]), description=str(row.get("description", ""))
        )
    for row in df.iter_rows(named=True):
        tag = str(row["tag"])
        parent = str(row.get("parent", ""))
        if parent and parent in G:
            G.add_edge(parent, tag)
    return G


def materialize_traversal_cache(
    build_ontology_graph: nx.DiGraph, config: Config
) -> dict:
    """Pre-compute ancestors, descendants, and subtree for each tag."""
    cache = {}
    for node in build_ontology_graph.nodes:
        ancestors = list(nx.ancestors(build_ontology_graph, node))
        descendants = list(nx.descendants(build_ontology_graph, node))
        cache[node] = {
            "ancestors": sorted(ancestors),
            "descendants": sorted(descendants),
            "depth": build_ontology_graph.nodes[node].get("depth", 0),
        }
    return cache


def validate_ontology_constraints(
    build_ontology_graph: nx.DiGraph, config: Config
) -> dict:
    """Validate DAG: no cycles, single root, valid depths."""
    has_cycle = False
    try:
        cycle = list(nx.find_cycle(build_ontology_graph, orientation="ignore"))
        has_cycle = len(cycle) > 0
    except nx.NetworkXNoCycle:
        pass
    roots = [
        n for n in build_ontology_graph.nodes if build_ontology_graph.in_degree(n) == 0
    ]
    return {
        "is_dag": not has_cycle,
        "has_single_root": len(roots) == 1,
        "root_count": len(roots),
        "node_count": build_ontology_graph.number_of_nodes(),
    }


def build_tag_scope_index(build_ontology_graph: nx.DiGraph, config: Config) -> dict:
    """Map each tag to its descendant tags (tag → [descendant_tags])."""
    scope = {}
    for node in build_ontology_graph.nodes:
        descendants = nx.descendants(build_ontology_graph, node)
        scope[node] = sorted(descendants) if descendants else []
    return scope


def compute_ontology_statistics(
    build_ontology_graph: nx.DiGraph, config: Config
) -> dict:
    """Depth distribution, branch count, leaf tags for the ontology DAG."""
    depths = [data.get("depth", 0) for _, data in build_ontology_graph.nodes(data=True)]
    leaves = [
        n for n in build_ontology_graph.nodes if build_ontology_graph.out_degree(n) == 0
    ]
    return {
        "total_tags": build_ontology_graph.number_of_nodes(),
        "total_edges": build_ontology_graph.number_of_edges(),
        "max_depth": max(depths) if depths else 0,
        "leaf_count": len(leaves),
        "depth_distribution": {d: depths.count(d) for d in sorted(set(depths))},
    }


def build_combined_index_metadata(
    build_bm25: dict, build_ontology_graph: nx.DiGraph, config: Config
) -> dict:
    """Merged index descriptor combining BM25 and ontology stats."""
    bm25_meta = build_bm25.get("metadata", {})
    return {
        "bm25_corpus_size": bm25_meta.get("corpus_size", 0),
        "bm25_exemplar_count": bm25_meta.get("exemplar_count", 0),
        "ontology_node_count": build_ontology_graph.number_of_nodes(),
        "ontology_edge_count": build_ontology_graph.number_of_edges(),
    }
