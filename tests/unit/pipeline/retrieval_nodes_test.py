"""Tests for retrieval_nodes.py — 7 pure functions."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.nodes.retrieval_nodes import (  # noqa: E402
    build_query_context,
    compute_retrieval_statistics,
    format_retrieval_for_inference,
    rank_exemplar_candidates,
    retrieve_code_candidates,
    retrieve_interpretation_candidates,
    retrieve_theme_candidates,
)

CONFIG = Config(
    groq_api_key="test",
    groq_model="test",
    groq_timeout=30,
    groq_max_retries=1,
    code_temperature=0.3,
    theme_temperature=0.4,
    interpretation_temperature=0.5,
    embedding_model="test",
    model_cache_dir=Path("/tmp/cache"),
    batch_size=15,
    log_level="DEBUG",
    data_path=Path("/tmp/data.csv"),
    tags_path=Path("/tmp/tags.csv"),
    processed_data_path=Path("/tmp/processed"),
    bm25_tokenizer_config="lowercase,split_by_space",
    fewshot_enabled=False,
    fewshot_count=2,
    fewshot_shuffle=False,
    token_cost_input_per_million=0.15,
    token_cost_output_per_million=0.60,
    max_stage_cost_usd=1.0,
)

_EMB_384 = np.zeros(384, dtype=np.float32)


def _emb_lf(ids: list[int], tags: list[str] | None = None) -> pl.LazyFrame:
    d = {"id": ids, "embedding": [_EMB_384 for _ in ids]}
    if tags:
        d["tag"] = tags
    return pl.DataFrame(d).lazy()


def test_retrieve_code_candidates():
    lf = _emb_lf([1], tags=["root"])
    kw = pl.DataFrame(
        {
            "keyword_id": [1],
            "exemplar_id": [1],
            "keyword_text": ["stress"],
            "frequency": [1],
        }
    ).lazy()
    result = retrieve_code_candidates(
        embed_exemplars=lf,
        embed_keywords=kw,
        build_bm25={
            "bm25_object": None,
            "corpus": [],
            "entity_map": {},
            "metadata": {},
        },
        build_ontology_graph=nx.DiGraph(),
        build_tag_scope_index={},
        config=CONFIG,
    )
    assert isinstance(result, list)
    if result:
        eid, score = result[0]
        assert isinstance(eid, int)
        assert isinstance(score, float)


def test_retrieve_theme_candidates():
    lf = _emb_lf([1])
    result = retrieve_theme_candidates(
        embed_codes=lf,
        build_ontology_graph=nx.DiGraph(),
        build_tag_scope_index={},
        config=CONFIG,
    )
    assert isinstance(result, list)
    if result:
        eid, score = result[0]
        assert isinstance(eid, int)
        assert isinstance(score, float)


def test_retrieve_interpretation_candidates():
    lf = _emb_lf([1])
    result = retrieve_interpretation_candidates(
        embed_themes=lf,
        build_ontology_graph=nx.DiGraph(),
        build_tag_scope_index={},
        config=CONFIG,
    )
    assert isinstance(result, list)
    if result:
        eid, score = result[0]
        assert isinstance(eid, int)
        assert isinstance(score, float)


def test_build_query_context():
    candidates = [(1, 0.9), (2, 0.8)]
    result = build_query_context(candidates, CONFIG)
    assert result["candidate_count"] == 2
    assert len(result["top_candidates"]) == 2


def test_rank_exemplar_candidates():
    candidates = [(1, 0.9)]
    result = rank_exemplar_candidates(candidates, {}, CONFIG)
    assert result == candidates


def test_format_retrieval_for_inference():
    result = format_retrieval_for_inference([], CONFIG)
    assert "tag_exemplar_map" in result


def test_compute_retrieval_statistics():
    candidates = [(1, 0.9), (2, 0.8), (3, 0.7)]
    result = compute_retrieval_statistics(candidates, CONFIG)
    assert result["total_candidates"] == 3
    assert result["max_score"] == 0.9
    assert result["min_score"] == 0.7


def test_compute_retrieval_statistics_empty():
    result = compute_retrieval_statistics([], CONFIG)
    assert result["total_candidates"] == 0
