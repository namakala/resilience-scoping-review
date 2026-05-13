"""Hybrid retrieval orchestrator: scope -> BM25 -> embeddings -> rerank.

Implements ADR-006. Delegates each stage to a dedicated sub-module
and combines results via weighted rerank with proximity boost.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import duckdb
import numpy as np
from utils.logging import get_logger

from .candidates import resolve_candidate_ids
from .scoring import get_bm25_scores_for_candidates, get_depth, get_embedding_scores
from .weights import WeightConfig, select_weights

logger = get_logger(__name__)


def hybrid_retrieve(
    query_tag: str,
    query_keywords: list[str],
    query_embedding: np.ndarray,
    candidate_type: str,
    con: duckdb.DuckDBPyConnection,
    k: int = 50,
    model_hash: Optional[str] = None,
) -> list[tuple[int, float]]:
    """Four-stage hybrid retrieval for semantic candidates.

    Stages:
        1. **Scope** — Restrict candidates to ontology subtree.
        2. **BM25** — Lexical scoring (exemplar only; skipped otherwise
           with renormalized weights).
        3. **Embedding** — Cosine similarity via cached embeddings.
        4. **Rerank** — Weighted sum of embedding, proximity, BM25.

    Args:
        query_tag: Ontology tag for candidate pool.
        query_keywords: Keywords for BM25 query.
        query_embedding: L2-normalized query vector.
        candidate_type: ``'exemplar'``, ``'code'``, ``'theme'``,
            or ``'interpretation'``.
        con: Active DuckDB connection.
        k: Number of top results. Default 50.
        model_hash: Optional embedding model version hash.

    Returns:
        List of ``(entity_id, score)`` sorted descending, ties broken
        by ascending entity_id.

    Raises:
        KeyError: If ``query_tag`` is not in the ontology DAG.
    """
    candidate_ids, entity_tag_map = resolve_candidate_ids(
        query_tag,
        candidate_type,
        con,
    )
    if not candidate_ids:
        return []

    w, bm25_scores, top_bm25 = _score_bm25_or_default(
        query_keywords,
        candidate_ids,
        candidate_type,
        k,
    )

    emb_scores, top_emb = get_embedding_scores(
        query_embedding,
        candidate_ids,
        candidate_type,
        con,
        model_hash,
        k,
    )

    return _rerank(
        top_bm25,
        top_emb,
        bm25_scores,
        emb_scores,
        entity_tag_map,
        query_tag,
        w,
        k,
    )


def _score_bm25_or_default(
    query_keywords: list[str],
    candidate_ids: set[int],
    candidate_type: str,
    k: int,
) -> Tuple[WeightConfig, Dict[int, float], set[int]]:
    """Run BM25 for exemplars; return empty defaults for other types."""
    if candidate_type == "exemplar":
        bm25_scores = get_bm25_scores_for_candidates(
            query_keywords,
            candidate_ids,
            k,
        )
        return select_weights("exemplar"), bm25_scores, set(bm25_scores.keys())
    return select_weights("non_exemplar"), {}, set()


def _rerank(
    top_bm25: set[int],
    top_emb: set[int],
    bm25_scores: Dict[int, float],
    emb_scores: Dict[int, float],
    entity_tag_map: Dict[int, str],
    query_tag: str,
    w: WeightConfig,
    k: int,
) -> list[tuple[int, float]]:
    """Union candidates, compute weighted score, sort, return top-k."""
    pool = top_bm25 | top_emb
    query_depth = get_depth(query_tag)

    finals: Dict[int, float] = {}
    for eid in pool:
        tag = entity_tag_map.get(eid)
        if tag is None:
            logger.warning(
                "Candidate has no tag mapping, skipping",
                extra={"entity_id": eid},
            )
            continue
        depth_dist = abs(get_depth(tag) - query_depth)
        prox = 1.0 / (1.0 + depth_dist)
        finals[eid] = (
            w.emb * emb_scores.get(eid, 0.0)
            + w.prox * prox
            + w.bm25 * bm25_scores.get(eid, 0.0)
        )

    return sorted(finals.items(), key=lambda x: (-x[1], x[0]))[:k]
