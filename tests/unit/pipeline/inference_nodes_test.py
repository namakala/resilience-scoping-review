"""Tests for inference_nodes.py — 10 pure functions."""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import polars as pl  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.nodes.inference_nodes import (  # noqa: E402
    infer_codes,
    infer_interpretations,
    infer_themes,
    init_groq_client,
    prepare_code_batches,
    prepare_code_nodes,
    prepare_interpretation_nodes,
    prepare_interpretation_spans,
    prepare_theme_batches,
    prepare_theme_nodes,
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


def test_init_groq_client():
    result = init_groq_client(CONFIG)
    assert result["model"] == "test"
    assert result["timeout"] == 30


def test_prepare_code_batches():
    import networkx as nx

    lf = pl.DataFrame({"id": [1, 2], "tag": ["A", "B"]}).lazy()
    dag = nx.DiGraph()
    dag.add_node("A", depth=0)
    dag.add_node("B", depth=0)
    result = prepare_code_batches(lf, dag, CONFIG)
    assert len(result) == 2


def test_prepare_code_batches_same_tag():
    import networkx as nx

    lf = pl.DataFrame({"id": [1, 2, 3], "tag": ["A", "A", "B"]}).lazy()
    dag = nx.DiGraph()
    dag.add_node("A", depth=0)
    dag.add_node("B", depth=0)
    result = prepare_code_batches(lf, dag, CONFIG)
    assert len(result) == 2  # 2 tags


@mock.patch("inference.groq_client.complete")
def test_infer_codes(mock_complete):
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "codes": [
                {
                    "exemplar_id": "1",
                    "code_name": "test",
                    "definition": "def",
                    "supporting_quote": "q",
                    "related_existing_codes": [],
                }
            ]
        }
    )
    mock_complete.return_value = mock_response

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock(id=1)]

    result = infer_codes(
        prepare_code_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        existing_codes=[],
        tag_metadata={},
    )
    assert len(result) == 1
    assert result[0].code_name == "test"


@mock.patch("inference.groq_client.complete")
def test_infer_codes_empty_batches(mock_complete):
    result = infer_codes([], {}, mock.MagicMock(), CONFIG)
    assert result == []


@mock.patch("inference.groq_client.complete")
def test_infer_themes(mock_complete):
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = (
        '{"themes": [{"theme_name": "T1", "narrative": "N", "code_ids": ["1"]}]}'
    )
    mock_complete.return_value = mock_response

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock()]

    result = infer_themes(
        prepare_theme_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        existing_theme_nodes=[],
        tag_metadata={},
    )
    assert len(result) == 1
    assert result[0].theme_name == "T1"


@mock.patch("inference.groq_client.complete")
def test_infer_interpretations(mock_complete):
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "interpretations": [
                {
                    "interpretation_name": "I1",
                    "narrative": "N",
                    "theme_ids": ["1"],
                    "key_insights": ["insight"],
                }
            ]
        }
    )
    mock_complete.return_value = mock_response

    result = infer_interpretations(
        prepare_interpretation_spans=[["A", "B"]],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        tag_metadata={},
    )
    assert len(result) == 1


def test_prepare_code_nodes():
    mock_code = mock.MagicMock()
    mock_code.code_name = "C1"
    mock_code.definition = "def"
    mock_code.tag = "A"
    result = prepare_code_nodes([mock_code], CONFIG)
    assert len(result) == 1
    assert result[0]["name"] == "C1"


def test_prepare_code_nodes_dedup():
    c1, c2 = mock.MagicMock(), mock.MagicMock()
    c1.code_name, c1.definition, c1.tag = "C1", "def", "A"
    c2.code_name, c2.definition, c2.tag = "C1", "def", "A"
    result = prepare_code_nodes([c1, c2], CONFIG)
    assert len(result) == 1


def test_prepare_theme_nodes():
    t = mock.MagicMock()
    t.theme_name, t.narrative, t.code_ids = "T1", "N", ["1"]
    result = prepare_theme_nodes([t], CONFIG)
    assert result[0]["theme_name"] == "T1"


def test_prepare_interpretation_nodes():
    i = mock.MagicMock()
    i.interpretation_name, i.narrative = "I1", "N"
    i.theme_ids = ["1"]
    result = prepare_interpretation_nodes([i], CONFIG)
    assert result[0]["interpretation_name"] == "I1"


def test_prepare_interpretation_spans():
    themes = [{"tag": "A"}, {"tag": "A"}, {"tag": "B"}]
    import networkx as nx

    result = prepare_interpretation_spans(themes, nx.DiGraph(), CONFIG)
    assert len(result) > 0


def test_prepare_theme_batches():
    codes = [
        {"id": 1, "name": "C1", "tag": "A"},
        {"id": 2, "name": "C2", "tag": "A"},
        {"id": 3, "name": "C3", "tag": "B"},
    ]
    import networkx as nx

    dag = nx.DiGraph()
    dag.add_node("A", depth=0)
    dag.add_node("B", depth=0)
    result = prepare_theme_batches(codes, dag, CONFIG)
    assert len(result) == 2
    for batch in result:
        assert len(batch.items) <= 5
        assert hasattr(batch, "tag")


def test_prepare_theme_batches_empty():
    result = prepare_theme_batches([], mock.MagicMock(), CONFIG)
    assert result == []


# ── Dirty flag tests (Feature 55) ───────────────────────────────────


@mock.patch("inference.groq_client.complete")
def test_infer_codes_skips_clean_batch(mock_complete):
    """infer_codes skips batches whose tag is NOT in dirty_flags."""

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock(id=1)]

    result = infer_codes(
        prepare_code_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={},
    )
    assert result == []
    mock_complete.assert_not_called()


@mock.patch("inference.groq_client.complete")
def test_infer_codes_processes_dirty_batch(mock_complete):
    """infer_codes processes batches whose tag IS in dirty_flags."""
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "codes": [
                {
                    "exemplar_id": "1",
                    "code_name": "test",
                    "definition": "def",
                    "supporting_quote": "q",
                    "related_existing_codes": [],
                }
            ]
        }
    )
    mock_complete.return_value = mock_response

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock(id=1)]

    result = infer_codes(
        prepare_code_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={"A": True},
    )
    assert len(result) == 1
    mock_complete.assert_called_once()


@mock.patch("inference.groq_client.complete")
def test_infer_codes_mixed_dirty_clean(mock_complete):
    """With 3 batches (A=dirty, B=clean, C=dirty), only A and C call Groq."""
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "codes": [
                {
                    "exemplar_id": "1",
                    "code_name": "test",
                    "definition": "def",
                    "supporting_quote": "q",
                    "related_existing_codes": [],
                }
            ]
        }
    )
    mock_complete.return_value = mock_response

    class MockBatch:
        def __init__(self, tag):
            self.tag = tag
            self.items = [mock.MagicMock(id=1)]

    result = infer_codes(
        prepare_code_batches=[MockBatch("A"), MockBatch("B"), MockBatch("C")],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={"A": True, "C": True},
    )
    assert len(result) == 2  # Only A and C produced results
    assert mock_complete.call_count == 2


@mock.patch("inference.groq_client.complete")
def test_infer_themes_skips_clean_batch(mock_complete):
    """infer_themes skips batches whose tag is NOT in dirty_flags."""

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock()]

    result = infer_themes(
        prepare_theme_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={},
    )
    assert result == []
    mock_complete.assert_not_called()


@mock.patch("inference.groq_client.complete")
def test_infer_themes_processes_dirty_batch(mock_complete):
    """infer_themes processes batches whose tag IS in dirty_flags."""
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = (
        '{"themes": [{"theme_name": "T1", "narrative": "N", "code_ids": ["1"]}]}'
    )
    mock_complete.return_value = mock_response

    class MockBatch:
        tag = "A"
        items = [mock.MagicMock()]

    result = infer_themes(
        prepare_theme_batches=[MockBatch()],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={"A": True},
    )
    assert len(result) == 1
    mock_complete.assert_called_once()


@mock.patch("inference.groq_client.complete")
def test_infer_interpretations_skips_clean_span(mock_complete):
    """infer_interpretations skips spans where NO tag is dirty."""
    result = infer_interpretations(
        prepare_interpretation_spans=[["A", "B"]],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={},
    )
    assert result == []
    mock_complete.assert_not_called()


@mock.patch("inference.groq_client.complete")
def test_infer_interpretations_processes_dirty_span(mock_complete):
    """infer_interpretations processes spans where ANY tag is dirty."""
    mock_response = mock.MagicMock()
    mock_response.choices = [mock.MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "interpretations": [
                {
                    "interpretation_name": "I1",
                    "narrative": "N",
                    "theme_ids": ["1"],
                    "key_insights": ["insight"],
                }
            ]
        }
    )
    mock_complete.return_value = mock_response

    result = infer_interpretations(
        prepare_interpretation_spans=[["A", "B"]],
        init_groq_client={},
        build_ontology_graph=mock.MagicMock(),
        config=CONFIG,
        dirty_flags={"A": True},
    )
    assert len(result) == 1
    mock_complete.assert_called_once()
