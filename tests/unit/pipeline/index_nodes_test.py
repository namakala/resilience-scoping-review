"""Tests for index_nodes.py — 7 pure functions."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import networkx as nx  # noqa: E402
import polars as pl  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.nodes.index_nodes import (  # noqa: E402
    build_bm25,
    build_combined_index_metadata,
    build_ontology_graph,
    build_tag_scope_index,
    compute_ontology_statistics,
    materialize_traversal_cache,
    validate_ontology_constraints,
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


def _tag_lf(tags: list[tuple[str, str, int]]) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "tag": [t[0] for t in tags],
            "parent": [t[1] for t in tags],
            "description": ["" for _ in tags],
            "depth": [t[2] for t in tags],
        }
    ).lazy()


def test_build_bm25():
    kw = pl.DataFrame(
        {
            "keyword_id": [1, 2],
            "exemplar_id": [1, 2],
            "keyword_text": ["stress", "coping"],
            "frequency": [1, 1],
        }
    ).lazy()
    result = build_bm25(kw, CONFIG)
    assert "bm25_object" in result
    assert result["metadata"]["corpus_size"] == 2


def test_build_ontology_graph():
    lf = _tag_lf([("root", "", 0), ("root.A", "root", 1)])
    G = build_ontology_graph(lf, CONFIG)
    assert G.number_of_nodes() == 2
    assert G.has_edge("root", "root.A")


def test_build_ontology_graph_single_node():
    lf = _tag_lf([("root", "", 0)])
    G = build_ontology_graph(lf, CONFIG)
    assert G.number_of_nodes() == 1


def test_materialize_traversal_cache():
    G = nx.DiGraph()
    G.add_node("root", depth=0)
    G.add_node("root.A", depth=1)
    G.add_edge("root", "root.A")
    cache = materialize_traversal_cache(G, CONFIG)
    assert "root" in cache
    assert cache["root"]["descendants"] == ["root.A"]
    assert cache["root.A"]["ancestors"] == ["root"]


def test_validate_ontology_constraints():
    G = nx.DiGraph()
    G.add_node("root", depth=0)
    result = validate_ontology_constraints(G, CONFIG)
    assert result["is_dag"]
    assert result["has_single_root"]


def test_build_tag_scope_index():
    G = nx.DiGraph()
    G.add_node("root", depth=0)
    G.add_node("root.A", depth=1)
    G.add_node("root.A.B", depth=2)
    G.add_edge("root", "root.A")
    G.add_edge("root.A", "root.A.B")
    scope = build_tag_scope_index(G, CONFIG)
    assert "root.A.B" in scope["root"]
    assert scope["root.A"] == ["root.A.B"]


def test_compute_ontology_statistics():
    G = nx.DiGraph()
    G.add_node("root", depth=0)
    G.add_node("root.A", depth=1)
    G.add_node("root.A.B", depth=2)
    G.add_edge("root", "root.A")
    G.add_edge("root.A", "root.A.B")
    stats = compute_ontology_statistics(G, CONFIG)
    assert stats["total_tags"] == 3
    assert stats["max_depth"] == 2
    assert stats["leaf_count"] == 1


def test_build_combined_index_metadata():
    bm25 = {"metadata": {"corpus_size": 50, "exemplar_count": 10}}
    G = nx.DiGraph()
    G.add_node("root", depth=0)
    meta = build_combined_index_metadata(bm25, G, CONFIG)
    assert meta["bm25_corpus_size"] == 50
    assert meta["ontology_node_count"] == 1


def test_validate_ontology_constraints_cycle():
    G = nx.DiGraph()
    G.add_node("A", depth=0)
    G.add_node("B", depth=1)
    G.add_edge("A", "B")
    G.add_edge("B", "A")  # creates cycle
    result = validate_ontology_constraints(G, CONFIG)
    assert not result["is_dag"]
    assert result["node_count"] == 2


def test_build_bm25_custom_tokenizer():
    kw = pl.DataFrame(
        {
            "keyword_id": [1],
            "exemplar_id": [1],
            "keyword_text": ["STRESS coping"],
            "frequency": [1],
        },
    ).lazy()
    # Use lowercase + stopword removal
    cfg = Config(
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
        bm25_tokenizer_config="lowercase,split_by_space,remove_stopword",
        fewshot_enabled=False,
        fewshot_count=2,
        fewshot_shuffle=False,
        token_cost_input_per_million=0.15,
        token_cost_output_per_million=0.60,
        max_stage_cost_usd=1.0,
    )
    result = build_bm25(kw, cfg)
    assert (
        result["metadata"]["tokenizer_config"]
        == "lowercase,split_by_space,remove_stopword"
    )
    # "coping" should survive stopword removal, "STRESS" becomes "stress"
    # Both should be in the corpus tokens
    assert len(result["corpus"]) == 1
    tokens = result["corpus"][0]
    assert "coping" in tokens
    assert "stress" in tokens
