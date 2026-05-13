"""Scoring helpers for hybrid retrieval: BM25, embeddings, ontology depth.

Each function is self-contained and independently testable.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

import duckdb
import numpy as np
from ontology.dag import get_tag_dag
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

from ..api import get_scores

logger = get_logger(__name__)


def get_bm25_scores_for_candidates(
    query_keywords: List[str],
    candidate_ids: Set[int],
    k: int,
) -> Dict[int, float]:
    """Score candidates by BM25 and return top-k scores.

    Joins ``query_keywords`` into a single string for the BM25 API,
    then filters by ``candidate_ids`` and returns the top-k.

    Args:
        query_keywords: Keywords to join into a query string.
        candidate_ids: Restrict scoring to these entity IDs.
        k: Number of top scores to return.

    Returns:
        Dict of ``{entity_id: score}`` for the top-k candidates.
    """
    query = " ".join(query_keywords)
    all_scores = get_scores(query)
    filtered = {eid: s for eid, s in all_scores.items() if eid in candidate_ids}
    top_k = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:k]
    return dict(top_k)


def get_embedding_scores(
    query_embedding: np.ndarray,
    candidate_ids: Set[int],
    candidate_type: str,
    con: duckdb.DuckDBPyConnection,
    model_hash: Optional[str],
    k: int,
) -> Tuple[Dict[int, float], Set[int]]:
    """Cosine similarity between query embedding and each candidate.

    Loads embeddings from the cache (skipping cache misses). Uses dot
    product since embeddings are L2-normalized.

    Args:
        query_embedding: L2-normalized query vector.
        candidate_ids: Entities to score.
        candidate_type: Entity type for cache lookup.
        con: Active DuckDB connection.
        model_hash: Optional model version hash.
        k: Number of top results.

    Returns:
        ``(scores_dict, top_k_id_set)``.
    """
    embeddings: List[np.ndarray] = []
    valid_ids: List[int] = []
    for cid in candidate_ids:
        emb = get_embedding(con, str(cid), candidate_type, model_hash)
        if emb is not None:
            embeddings.append(emb)
            valid_ids.append(cid)

    if not embeddings:
        logger.warning(
            "No embeddings found for any candidate",
            extra={
                "candidate_count": len(candidate_ids),
                "type": candidate_type,
            },
        )
        return {}, set()

    matrix = np.stack(embeddings, axis=0)
    similarities = query_embedding @ matrix.T

    scores: Dict[int, float] = {}
    for i, cid in enumerate(valid_ids):
        scores[cid] = float(similarities[i])

    top_k_items = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:k]
    return scores, {eid for eid, _ in top_k_items}


def get_depth(tag: str) -> int:
    """Get ontology depth of a tag. Root = 0.

    If the tag is not in the ontology DAG, logs a warning and
    returns 0.

    Args:
        tag: Ontology tag string.

    Returns:
        Depth integer.
    """
    G = get_tag_dag()
    if tag not in G:
        logger.warning(
            "Tag not found in DAG, assuming depth 0",
            extra={"tag": tag},
        )
        return 0
    return int(G.nodes[tag].get("depth", 0))
