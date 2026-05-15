"""Scoring helpers for hybrid retrieval: BM25, embeddings, ontology depth.

Pure functions — every data dependency is an explicit parameter.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
from utils.logging import get_logger

from ..api import get_scores

logger = get_logger(__name__)

__all__ = [
    "get_bm25_scores_for_candidates",
    "get_embedding_scores",
    "get_depth",
]


def get_bm25_scores_for_candidates(
    query_keywords: list[str],
    candidate_ids: set[int],
    k: int,
    bm25_index: dict,
) -> dict[int, float]:
    """Score candidates by BM25 and return top-k.

    Parameters
    ----------
    query_keywords :
        Keywords to join into a query string.
    candidate_ids :
        Restrict scoring to these entity IDs.
    k :
        Maximum results to return.
    bm25_index :
        BM25 index dict as returned by :func:`build_index`.

    Returns
    -------
    dict
        ``{entity_id: score}`` for the top-k candidates.
    """
    query = " ".join(query_keywords)
    all_scores = get_scores(query, bm25_index)
    filtered = {eid: s for eid, s in all_scores.items() if eid in candidate_ids}
    top_k = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:k]
    return dict(top_k)


def get_embedding_scores(
    query_embedding: np.ndarray,
    embeddings_map: dict[int, np.ndarray],
    k: int,
) -> tuple[dict[int, float], set[int]]:
    """Cosine similarity between query embedding and candidate embeddings.

    Uses dot product (embeddings are assumed L2-normalized).  Candidates
    not present in *embeddings_map* are silently skipped.

    Parameters
    ----------
    query_embedding :
        L2-normalized query vector.
    embeddings_map :
        Entity ID → L2-normalized embedding vector.
    k :
        Maximum results to return.

    Returns
    -------
    tuple[dict[int, float], set[int]]
        ``(scores_dict, top_k_id_set)``.
    """
    valid_ids: list[int] = []
    embeddings: list[np.ndarray] = []

    for cid, emb in embeddings_map.items():
        valid_ids.append(cid)
        embeddings.append(emb)

    if not embeddings:
        logger.warning("No embeddings found for any candidate")
        return {}, set()

    matrix = np.stack(embeddings, axis=0)
    similarities = query_embedding @ matrix.T

    scores: dict[int, float] = {
        cid: float(similarities[i]) for i, cid in enumerate(valid_ids)
    }

    top_k_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return scores, {eid for eid, _ in top_k_items}


def get_depth(tag: str, ontology_graph: nx.DiGraph) -> int:
    """Ontology depth of a tag.  Root = 0.

    If the tag is not in the graph, logs a warning and returns 0.

    Parameters
    ----------
    tag :
        Ontology tag string.
    ontology_graph :
        NetworkX DiGraph with ``depth`` node attributes.

    Returns
    -------
    int
        Depth (0 for root).
    """
    if tag not in ontology_graph:
        logger.warning("Tag not found in DAG, assuming depth 0", extra={"tag": tag})
        return 0
    return int(ontology_graph.nodes[tag].get("depth", 0))
