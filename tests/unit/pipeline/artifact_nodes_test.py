"""Tests for artifact_nodes.py — 7 pure functions, no DB."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import networkx as nx  # noqa: E402
import polars as pl  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.nodes.artifact_nodes import (  # noqa: E402
    compute_exemplar_statistics,
    load_exemplars,
    load_keywords,
    load_tags,
    prepare_artifact_summary,
    resolve_tag_dag,
    validate_artifact_schemas,
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


def _mock_lf(columns: dict) -> pl.LazyFrame:
    return pl.DataFrame(columns).lazy()


@mock.patch("persistence.loaders.load_exemplars")
def test_load_exemplars(mock_load):
    mock_load.return_value = _mock_lf({"id": [1], "content": ["test"]})
    result = load_exemplars(CONFIG)
    assert isinstance(result, pl.LazyFrame)


@mock.patch("persistence.loaders.load_tags")
def test_load_tags(mock_load):
    mock_load.return_value = _mock_lf({"tag": ["root"], "description": ["test"]})
    result = load_tags(CONFIG)
    assert isinstance(result, pl.LazyFrame)


@mock.patch("persistence.loaders.load_keywords")
def test_load_keywords(mock_load):
    mock_load.return_value = _mock_lf({"keyword_id": [1], "keyword_text": ["test"]})
    result = load_keywords(CONFIG)
    assert isinstance(result, pl.LazyFrame)


def test_resolve_tag_dag():
    lf = _mock_lf(
        {
            "tag": ["root", "root.A"],
            "parent": ["", "root"],
            "description": ["", ""],
            "depth": [0, 1],
        }
    )
    graph = resolve_tag_dag(lf, CONFIG)
    assert isinstance(graph, nx.DiGraph)
    assert graph.number_of_nodes() == 2
    assert graph.has_edge("root", "root.A")


def test_validate_artifact_schemas_valid():
    ex = _mock_lf(
        {
            "id": [1],
            "document": ["d"],
            "tag": ["t"],
            "content": ["c"],
            "keywords": [["k"]],
        }
    )
    tg = _mock_lf({"tag": ["t"], "parent": [""], "description": [""]})
    kw = _mock_lf({"keyword_id": [1], "exemplar_id": [1], "keyword_text": ["k"]})
    result = validate_artifact_schemas(ex, tg, kw, CONFIG)
    assert all(result[name]["valid"] for name in result)


def test_compute_exemplar_statistics():
    lf = _mock_lf({"id": [1, 2], "tag": ["A", "B"]})
    result = compute_exemplar_statistics(lf, CONFIG)
    assert result["total_exemplars"] == 2
    assert "A" in result["tag_distribution"]


def test_prepare_artifact_summary():
    ex = _mock_lf({"id": [1, 2]})
    tg = _mock_lf({"tag": ["A"]})
    kw = _mock_lf({"keyword_id": [1]})
    result = prepare_artifact_summary(ex, tg, kw, CONFIG)
    assert result["exemplar_count"] == 2
    assert result["tag_count"] == 1


def test_validate_artifact_schemas_missing_columns():
    ex = _mock_lf({"id": [1]})  # missing document, tag, content, keywords
    tg = _mock_lf({"tag": ["t"]})  # missing parent, description
    kw = _mock_lf({"keyword_id": [1]})  # missing exemplar_id, keyword_text
    result = validate_artifact_schemas(ex, tg, kw, CONFIG)
    assert not result["exemplars"]["valid"]
    assert not result["tags"]["valid"]
    assert not result["keywords"]["valid"]
    assert "document" in result["exemplars"]["missing_cols"]
    assert "description" in result["tags"]["missing_cols"]
    assert "keyword_text" in result["keywords"]["missing_cols"]
