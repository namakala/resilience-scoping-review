"""Tests for orchestration/export_formatters.py — pure format builders."""

from __future__ import annotations

import json

from orchestration.export_formatters import _build_csv, _build_json, _build_markdown

TAG = "Problem.Cause"

SAMPLE_CODES = [
    {
        "id": 1,
        "name": "C1",
        "definition": "First code",
        "tag": TAG,
        "status": "approved",
        "data_json": {"exemplar_ids": ["10", "11"]},
    },
    {
        "id": 2,
        "name": "C2",
        "definition": "Second code",
        "tag": TAG,
        "status": "approved",
        "data_json": {"exemplar_ids": ["12"]},
    },
]

SAMPLE_THEMES = [
    {
        "id": 10,
        "name": "T1",
        "definition": "First theme",
        "tag": TAG,
        "status": "approved",
        "data_json": {"code_ids": [1, 2]},
    },
]

SAMPLE_INTERPS = [
    {
        "id": 100,
        "name": "I1",
        "definition": "First interpretation",
        "tag": TAG,
        "status": "approved",
        "data_json": {"theme_ids": [10], "tag_spans": [TAG]},
    },
]

SAMPLE_EXEMPLARS = {
    "10": "Exemplar ten content.",
    "11": "Exemplar eleven\nmulti-line content.",
    "12": "Exemplar twelve content.",
}


# ── _build_json ──────────────────────────────────────────────────────


def test_build_json_structure():
    data = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS)
    assert "codes_by_tag" in data
    assert "themes_by_tag" in data
    assert "interpretations" in data

    tag_codes = data["codes_by_tag"][TAG]
    assert len(tag_codes) == 2
    c1 = tag_codes[0]
    assert c1["id"] == 1
    assert c1["name"] == "C1"
    assert c1["definition"] == "First code"
    assert c1["tag"] == TAG
    assert c1["exemplar_ids"] == ["10", "11"]

    tag_themes = data["themes_by_tag"][TAG]
    assert len(tag_themes) == 1
    t1 = tag_themes[0]
    assert t1["id"] == 10
    assert t1["name"] == "T1"
    assert t1["narrative"] == "First theme"
    assert t1["tag"] == TAG
    assert t1["code_ids"] == [1, 2]

    interp = data["interpretations"][0]
    assert interp["id"] == 100
    assert interp["name"] == "I1"
    assert interp["narrative"] == "First interpretation"
    assert interp["theme_ids"] == [10]
    assert interp["tag_spans"] == [TAG]


def test_build_json_deterministic():
    data1 = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS)
    data2 = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS)
    assert json.dumps(data1, sort_keys=True) == json.dumps(data2, sort_keys=True)


def test_build_json_empty():
    data = _build_json([], [], [])
    assert data == {"codes_by_tag": {}, "themes_by_tag": {}, "interpretations": []}


# ── _build_csv ───────────────────────────────────────────────────────


def test_build_csv_flattening():
    rows = _build_csv(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert len(rows) == 3  # 2 + 1 exemplars across 2 codes in 1 theme in 1 interp
    for row in rows:
        assert row["interpretation_id"] == "100"
        assert row["interpretation_name"] == "I1"
        assert row["theme_id"] == "10"
        assert row["theme_name"] == "T1"
    eids = [r["exemplar_id"] for r in rows]
    assert "10" in eids
    assert "11" in eids
    assert "12" in eids


def test_build_csv_columns():
    rows = _build_csv(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    expected = [
        "interpretation_id",
        "interpretation_name",
        "theme_id",
        "theme_name",
        "code_id",
        "code_name",
        "exemplar_id",
        "exemplar_content",
        "tag_path",
    ]
    assert list(rows[0].keys()) == expected


def test_build_csv_empty():
    rows = _build_csv([], [], [], {})
    assert rows == []


def test_build_csv_no_exemplars():
    codes_no_ex = [
        {
            "id": 1,
            "name": "C1",
            "definition": "d",
            "tag": TAG,
            "status": "approved",
            "data_json": {"exemplar_ids": []},
        }
    ]
    themes_no_ex = [
        {
            "id": 10,
            "name": "T1",
            "definition": "d",
            "tag": TAG,
            "status": "approved",
            "data_json": {"code_ids": [1]},
        }
    ]
    interps_no_ex = [
        {
            "id": 100,
            "name": "I1",
            "definition": "d",
            "tag": TAG,
            "status": "approved",
            "data_json": {"theme_ids": [10]},
        }
    ]
    rows = _build_csv(interps_no_ex, themes_no_ex, codes_no_ex, {})
    assert len(rows) == 1
    assert rows[0]["exemplar_id"] == ""


# ── _build_markdown ──────────────────────────────────────────────────


def test_build_markdown_toc():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert "# Interpretations" in md
    assert "- [I1]" in md or "- [I1](#i1)" in md


def test_build_markdown_full_content():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert "Exemplar ten content." in md
    assert "Exemplar twelve content." in md
    assert "> Exemplar ten content." in md


def test_build_markdown_multi_line_content():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert "> Exemplar eleven" in md
    assert "> multi-line content." in md


def test_build_markdown_empty():
    md = _build_markdown([], [], [], {})
    assert "# Interpretations" in md
    assert md.strip() == "# Interpretations"
