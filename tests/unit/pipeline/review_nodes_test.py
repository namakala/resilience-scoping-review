"""Tests for review_nodes.py — 6 identity function tests."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from pipeline.config import Config  # noqa: E402
from pipeline.nodes.review_nodes import (  # noqa: E402
    apply_code_edits,
    apply_interpretation_edits,
    apply_theme_edits,
    review_codes,
    review_interpretations,
    review_themes,
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
    export_output_path=Path("/tmp/export"),
)


def test_review_codes_identity():
    codes = [{"name": "C1", "definition": "def"}]
    result = review_codes(codes, CONFIG)
    assert result == codes


def test_review_codes_empty():
    assert review_codes([], CONFIG) == []


def test_review_themes_identity():
    themes = [{"theme_name": "T1"}]
    result = review_themes(themes, CONFIG)
    assert result == themes


def test_review_interpretations_identity():
    interps = [{"interpretation_name": "I1"}]
    result = review_interpretations(interps, CONFIG)
    assert result == interps


def test_apply_code_edits():
    codes = [{"name": "C1"}]
    assert apply_code_edits(codes, CONFIG) == codes


def test_apply_theme_edits():
    themes = [{"theme_name": "T1"}]
    assert apply_theme_edits(themes, CONFIG) == themes


def test_apply_interpretation_edits():
    interps = [{"interpretation_name": "I1"}]
    assert apply_interpretation_edits(interps, CONFIG) == interps
