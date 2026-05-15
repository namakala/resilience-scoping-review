"""Tests for embedding_nodes.py — 8 pure functions."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.nodes.embedding_nodes import (  # noqa: E402
    cache_exemplar_embeddings,
    cache_keyword_embeddings,
    embed_codes,
    embed_exemplars,
    embed_keywords,
    embed_themes,
    init_embedding_model,
    verify_embedding_integrity,
)

CONFIG = Config(
    groq_api_key="test",
    groq_model="test",
    groq_timeout=30,
    groq_max_retries=1,
    code_temperature=0.3,
    theme_temperature=0.4,
    interpretation_temperature=0.5,
    embedding_model="all-MiniLM-L6-v2",
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


def test_init_embedding_model():
    result = init_embedding_model(CONFIG)
    assert result == "all-MiniLM-L6-v2"


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_embed_exemplars(mock_gen):
    mock_gen.return_value = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    lf = pl.DataFrame(
        {"id": [1, 2], "content": ["a", "b"], "keywords": [[], []]}
    ).lazy()
    result = embed_exemplars(lf, "model", CONFIG)
    df = result.collect()
    assert "embedding" in df.columns
    assert df.height == 2


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_embed_keywords(mock_gen):
    mock_gen.return_value = np.array([[0.1]], dtype=np.float32)
    lf = pl.DataFrame({"keyword_id": [1], "keyword_text": ["stress"]}).lazy()
    result = embed_keywords(lf, "model", CONFIG)
    assert "embedding" in result.collect().columns


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_embed_codes(mock_gen):
    mock_gen.return_value = np.array([[0.1]], dtype=np.float32)
    codes = [{"id": 1, "code_name": "test", "definition": "a code"}]
    result = embed_codes(codes, "model", CONFIG)
    assert result.collect().height == 1


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_embed_themes(mock_gen):
    mock_gen.return_value = np.array([[0.1]], dtype=np.float32)
    themes = [{"id": 1, "theme_name": "t", "narrative": "n"}]
    result = embed_themes(themes, "model", CONFIG)
    assert result.collect().height == 1


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_embed_codes_empty(mock_gen):
    result = embed_codes([], "model", CONFIG)
    assert result.collect().height == 0


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_cache_exemplar_embeddings(mock_gen):
    mock_gen.return_value = np.array([[0.1]], dtype=np.float32)
    lf = pl.DataFrame(
        {"id": [1], "content": ["x"], "embedding": [[0.1]], "keywords": [[]]}
    ).lazy()
    result = cache_exemplar_embeddings(lf, CONFIG)
    assert result["entity_type"] == "exemplar"
    assert result["count"] == 1


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_cache_keyword_embeddings(mock_gen):
    mock_gen.return_value = np.array([[0.1]], dtype=np.float32)
    lf = pl.DataFrame(
        {"keyword_id": [1], "keyword_text": ["x"], "embedding": [[0.1]]}
    ).lazy()
    result = cache_keyword_embeddings(lf, CONFIG)
    assert result["entity_type"] == "keyword"


@mock.patch("pipeline.nodes.embedding_nodes._generate_embeddings")
def test_verify_embedding_integrity(mock_gen):
    mock_gen.return_value = np.array([[0.1, 0.0, 0.0] + [0.0] * 381], dtype=np.float32)
    lf = pl.DataFrame(
        {
            "id": [1],
            "content": ["x"],
            "embedding": [[0.1] + [0.0] * 383],
            "keywords": [[]],
        }
    ).lazy()
    kw = pl.DataFrame(
        {"keyword_id": [1], "keyword_text": ["x"], "embedding": [[0.1] + [0.0] * 383]}
    ).lazy()
    result = verify_embedding_integrity(lf, kw, CONFIG)
    assert "exemplars" in result
