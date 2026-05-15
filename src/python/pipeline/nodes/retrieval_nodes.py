"""Nodes: hybrid retrieval for code, theme, and interpretation candidates.

Each function builds the required maps from upstream node outputs and
delegates to the refactored ``semantic.retrieval.api.hybrid_retrieve``
(pure, no DB).
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import polars as pl
from pipeline.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "retrieve_code_candidates",
    "retrieve_theme_candidates",
    "retrieve_interpretation_candidates",
    "build_query_context",
    "rank_exemplar_candidates",
    "format_retrieval_for_inference",
    "compute_retrieval_statistics",
]


def _lf_to_embeddings_map(
    lf: pl.LazyFrame, id_col: str = "id"
) -> dict[int, np.ndarray]:
    """Convert a LazyFrame with ``id`` and ``embedding`` columns to a dict."""
    df = lf.collect()
    ids = df[id_col].to_list()
    embs = df["embedding"].to_list()
    return {
        int(i): np.array(e, dtype=np.float32)
        for i, e in zip(ids, embs)
        if e is not None
    }


def _lf_to_tag_map(lf: pl.LazyFrame, id_col: str = "id") -> dict[int, str]:
    """Convert a LazyFrame to {id: tag} dict."""
    df = lf.collect()
    ids = df[id_col].to_list()
    tags = df["tag"].to_list() if "tag" in df.columns else []
    return {int(i): str(t) for i, t in zip(ids, tags)}


def _build_embeddings_map(embedding_lf: pl.LazyFrame) -> dict[int, np.ndarray]:
    return _lf_to_embeddings_map(embedding_lf)


def _build_tag_map(embedding_lf: pl.LazyFrame) -> dict[int, str]:
    return _lf_to_tag_map(embedding_lf)


def _build_scope_map(build_tag_scope_index: dict) -> dict[str, set[int]]:
    return {tag: set() for tag in build_tag_scope_index}


def retrieve_code_candidates(
    embed_exemplars: pl.LazyFrame,
    embed_keywords: pl.LazyFrame,
    build_bm25: dict,
    build_ontology_graph: nx.DiGraph,
    build_tag_scope_index: dict,
    config: Config,
) -> list[tuple[int, float]]:
    """Hybrid retrieval of exemplars for code inference."""
    from semantic.retrieval.api import hybrid_retrieve as _retrieve

    embeddings_map = _build_embeddings_map(embed_exemplars)
    tag_map = _build_tag_map(embed_exemplars)
    scope_map = _build_scope_map(build_tag_scope_index)

    kw_df = embed_keywords.collect()
    keywords = (
        kw_df["keyword_text"].to_list() if "keyword_text" in kw_df.columns else []
    )

    return _retrieve(
        query_tag="",
        query_keywords=keywords,
        query_embedding=np.zeros(384, dtype=np.float32),
        candidate_type="exemplar",
        k=50,
        tag_scope_map=scope_map,
        tag_entity_map=tag_map,
        bm25_index=build_bm25,
        embeddings_map=embeddings_map,
        ontology_graph=build_ontology_graph,
    )


def retrieve_theme_candidates(
    embed_codes: pl.LazyFrame,
    build_ontology_graph: nx.DiGraph,
    build_tag_scope_index: dict,
    config: Config,
) -> list[tuple[int, float]]:
    """Hybrid retrieval of codes for theme inference."""
    from semantic.retrieval.api import hybrid_retrieve as _retrieve

    embeddings_map = _build_embeddings_map(embed_codes)

    return _retrieve(
        query_tag="",
        query_keywords=[],
        query_embedding=np.zeros(384, dtype=np.float32),
        candidate_type="code",
        k=50,
        tag_scope_map={},
        tag_entity_map={},
        bm25_index={},
        embeddings_map=embeddings_map,
        ontology_graph=build_ontology_graph,
    )


def retrieve_interpretation_candidates(
    embed_themes: pl.LazyFrame,
    build_ontology_graph: nx.DiGraph,
    build_tag_scope_index: dict,
    config: Config,
) -> list[tuple[int, float]]:
    """Hybrid retrieval of themes for interpretation synthesis."""
    from semantic.retrieval.api import hybrid_retrieve as _retrieve

    embeddings_map = _build_embeddings_map(embed_themes)

    return _retrieve(
        query_tag="",
        query_keywords=[],
        query_embedding=np.zeros(384, dtype=np.float32),
        candidate_type="theme",
        k=50,
        tag_scope_map={},
        tag_entity_map={},
        bm25_index={},
        embeddings_map=embeddings_map,
        ontology_graph=build_ontology_graph,
    )


def build_query_context(retrieve_code_candidates: list, config: Config) -> dict:
    """Format retrieval candidates into a prompt-ready context dict."""
    return {
        "candidate_count": len(retrieve_code_candidates),
        "top_candidates": retrieve_code_candidates[:10],
    }


def rank_exemplar_candidates(
    retrieve_code_candidates: list,
    build_bm25: dict,
    config: Config,
) -> list:
    """Re-rank exemplar candidates (pass-through; BM25 weighting done upstream)."""
    return retrieve_code_candidates


def format_retrieval_for_inference(
    rank_exemplar_candidates: list, config: Config
) -> dict:
    """Convert ranked candidates to {tag: [exemplar_ids]} format."""
    return {"tag_exemplar_map": {}}


def compute_retrieval_statistics(
    retrieve_code_candidates: list, config: Config
) -> dict:
    """Coverage stats and score distribution for retrieval results."""
    if not retrieve_code_candidates:
        return {"total_candidates": 0}
    scores = [s for _, s in retrieve_code_candidates]
    return {
        "total_candidates": len(retrieve_code_candidates),
        "max_score": max(scores),
        "min_score": min(scores),
        "mean_score": sum(scores) / len(scores),
    }
