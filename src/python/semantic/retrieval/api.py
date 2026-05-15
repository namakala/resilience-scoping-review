"""Hybrid retrieval orchestrator: scope → BM25 → embeddings → rerank.

Implements ADR-006.  Pure function — every data dependency is an explicit
parameter (no DuckDB, no global caches).  Callers (Hamilton DAG nodes or
orchestration code) build the required maps and graphs up front.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
from utils.logging import get_logger

from .candidates import resolve_candidate_ids
from .scoring import get_bm25_scores_for_candidates, get_depth, get_embedding_scores
from .weights import WeightConfig, select_weights

logger = get_logger(__name__)

__all__ = ["hybrid_retrieve"]


def hybrid_retrieve(
    query_tag: str,
    query_keywords: list[str],
    query_embedding: np.ndarray,
    candidate_type: str,
    k: int,
    tag_scope_map: dict[str, set[int]],
    tag_entity_map: dict[int, str],
    bm25_index: dict,
    embeddings_map: dict[int, np.ndarray],
    ontology_graph: nx.DiGraph,
    weights: WeightConfig | None = None,
) -> list[tuple[int, float]]:
    """Four-stage hybrid retrieval.

    Stages
    ------
    1. **Scope** — Restrict candidates via ``tag_scope_map``.
    2. **BM25** — Lexical scoring (exemplar only; skipped for other types
       via weight config).
    3. **Embedding** — Cosine similarity from ``embeddings_map``.
    4. **Rerank** — Weighted sum of embedding, proximity, BM25.

    Parameters
    ----------
    query_tag :
        Ontology tag for proximity computation.
    query_keywords :
        Keywords for BM25 query string.
    query_embedding :
        L2-normalized query vector.
    candidate_type :
        ``'exemplar'``, ``'code'``, ``'theme'``, or ``'interpretation'``.
    k :
        Number of top results to return.
    tag_scope_map :
        Tag → set of entity IDs for non-exemplar types.
    tag_entity_map :
        Entity ID → tag string.
    bm25_index :
        BM25 index dict (see :func:`semantic.index_builder.build_index`).
    embeddings_map :
        Entity ID → L2-normalized embedding vector.
    ontology_graph :
        NetworkX DiGraph with ``depth`` node attributes.
    weights :
        Optional weight override.  Defaults to
        :func:`select_weights(candidate_type)
        <semantic.retrieval.weights.select_weights>`.

    Returns
    -------
    list[tuple[int, float]]
        ``(entity_id, score)`` sorted descending, ties broken by
        ascending entity_id.
    """
    candidate_ids, entity_tag_map = resolve_candidate_ids(
        candidate_type=candidate_type,
        tag_scope_map=tag_scope_map,
        tag_entity_map=tag_entity_map,
    )
    if not candidate_ids:
        return []

    w_used, bm25_scores, top_bm25 = _score_bm25_or_default(
        query_keywords,
        candidate_ids,
        candidate_type,
        k,
        bm25_index,
        weights=weights,
    )

    emb_scores, top_emb = get_embedding_scores(
        query_embedding,
        embeddings_map,
        k,
    )

    return _rerank(
        top_bm25,
        top_emb,
        bm25_scores,
        emb_scores,
        entity_tag_map,
        query_tag,
        w_used,
        ontology_graph,
        k,
    )


def _score_bm25_or_default(
    query_keywords: list[str],
    candidate_ids: set[int],
    candidate_type: str,
    k: int,
    bm25_index: dict,
    weights: WeightConfig | None = None,
) -> tuple[WeightConfig, dict[int, float], set[int]]:
    """BM25 for exemplars; empty defaults for other types."""
    if candidate_type == "exemplar":
        bm25_scores = get_bm25_scores_for_candidates(
            query_keywords,
            candidate_ids,
            k,
            bm25_index,
        )
        return (
            weights or select_weights("exemplar"),
            bm25_scores,
            set(bm25_scores.keys()),
        )
    return weights or select_weights("non_exemplar"), {}, set()


def _rerank(
    top_bm25: set[int],
    top_emb: set[int],
    bm25_scores: dict[int, float],
    emb_scores: dict[int, float],
    entity_tag_map: dict[int, str],
    query_tag: str,
    w: WeightConfig,
    ontology_graph: nx.DiGraph,
    k: int,
) -> list[tuple[int, float]]:
    """Union candidates, weighted score, sort, return top-k."""
    pool = top_bm25 | top_emb
    query_depth = get_depth(query_tag, ontology_graph)

    finals: dict[int, float] = {}
    for eid in pool:
        tag = entity_tag_map.get(eid)
        if tag is None:
            logger.warning("Candidate has no tag, skipping", extra={"entity_id": eid})
            continue
        depth_dist = abs(get_depth(tag, ontology_graph) - query_depth)
        prox = 1.0 / (1.0 + depth_dist)
        finals[eid] = (
            w.emb * emb_scores.get(eid, 0.0)
            + w.prox * prox
            + w.bm25 * bm25_scores.get(eid, 0.0)
        )

    return sorted(finals.items(), key=lambda x: (-x[1], x[0]))[:k]
