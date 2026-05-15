"""Tests for export_nodes.py — 5 pure formatting functions."""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from pipeline.config import Config  # noqa: E402
from pipeline.nodes.export_nodes import (  # noqa: E402
    export_codes,
    export_combined,
    export_interpretations,
    export_summary,
    export_themes,
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


def test_export_codes():
    codes = [{"name": "C1", "definition": "def"}]
    result = export_codes(codes, CONFIG)
    assert result["count"] == 1
    assert result["codes"] == codes


def test_export_codes_empty():
    result = export_codes([], CONFIG)
    assert result["count"] == 0


def test_export_themes():
    themes = [{"theme_name": "T1", "narrative": "N"}]
    result = export_themes(themes, CONFIG)
    assert result["count"] == 1


def test_export_interpretations():
    interps = [{"interpretation_name": "I1"}]
    result = export_interpretations(interps, CONFIG)
    assert result["count"] == 1


def test_export_combined():
    codes = {"codes": [{"name": "C1"}], "count": 1}
    themes = {"themes": [{"theme_name": "T1"}], "count": 1}
    interps = {"interpretations": [{"interpretation_name": "I1"}], "count": 1}
    result = export_combined(codes, themes, interps, CONFIG)
    assert "codes" in result
    assert "themes" in result
    assert "interpretations" in result
    assert "summary" in result
    assert len(result["codes"]) == 1
    assert result["summary"]["code_count"] == 1
    assert result["summary"]["theme_count"] == 1
    assert result["summary"]["interpretation_count"] == 1


def test_export_summary():
    combined = {
        "codes": [{"name": "C1"}],
        "themes": [{"theme_name": "T1"}],
        "interpretations": [{"interpretation_name": "I1"}],
        "summary": {"code_count": 1, "theme_count": 1, "interpretation_count": 1},
    }
    result = export_summary(combined, CONFIG)
    assert result["code_count"] == 1
    assert result["theme_count"] == 1
    assert result["interpretation_count"] == 1


def test_export_summary_empty():
    combined = {
        "codes": [],
        "themes": [],
        "interpretations": [],
        "summary": {"code_count": 0, "theme_count": 0, "interpretation_count": 0},
    }
    result = export_summary(combined, CONFIG)
    assert result["code_count"] == 0
