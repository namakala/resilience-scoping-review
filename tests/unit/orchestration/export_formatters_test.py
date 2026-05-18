"""Tests for orchestration/export_formatters.py — pure format builders."""

from __future__ import annotations

import json

from orchestration.export_formatters import (
    CSV_COLUMNS,
    _build_csv,
    _build_json,
    _build_markdown,
)

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

# New format: dict of dicts keyed by id string, with full exemplar data
SAMPLE_EXEMPLARS = {
    "10": {
        "id": 10,
        "document": "doc1",
        "tag": TAG,
        "content": "Exemplar ten content.",
        "keywords": ["kw1", "kw2"],
    },
    "11": {
        "id": 11,
        "document": "doc1",
        "tag": TAG,
        "content": "Exemplar eleven\nmulti-line content.",
        "keywords": ["kw3"],
    },
    "12": {
        "id": 12,
        "document": "doc2",
        "tag": TAG,
        "content": "Exemplar twelve content.",
        "keywords": [],
    },
}


# ── _build_json ──────────────────────────────────────────────────────


def test_build_json_structure():
    data = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS, SAMPLE_EXEMPLARS)
    assert isinstance(data, list)
    assert len(data) == 1  # one interpretation

    interp = data[0]
    assert interp["id"] == 100
    assert interp["interpretation"] == "I1"
    assert interp["narrative"] == "First interpretation"

    themes = interp["themes"]
    assert len(themes) == 1
    theme = themes[0]
    assert theme["id"] == 10
    assert theme["name"] == "T1"
    assert theme["description"] == "First theme"

    codes = theme["codes"]
    assert len(codes) == 2

    c1 = codes[0]
    assert c1["id"] == 1
    assert c1["name"] == "C1"
    assert c1["description"] == "First code"
    assert c1["tag"] == TAG

    exemplars_c1 = c1["exemplars"]
    assert len(exemplars_c1) == 2
    assert exemplars_c1[0]["id"] == 10
    assert exemplars_c1[0]["content"] == "Exemplar ten content."
    assert exemplars_c1[0]["keywords"] == ["kw1", "kw2"]

    c2 = codes[1]
    assert c2["id"] == 2
    assert c2["name"] == "C2"
    assert len(c2["exemplars"]) == 1
    assert c2["exemplars"][0]["id"] == 12
    assert c2["exemplars"][0]["keywords"] == []


def test_build_json_deterministic():
    data1 = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS, SAMPLE_EXEMPLARS)
    data2 = _build_json(SAMPLE_CODES, SAMPLE_THEMES, SAMPLE_INTERPS, SAMPLE_EXEMPLARS)
    assert json.dumps(data1, sort_keys=True) == json.dumps(data2, sort_keys=True)


def test_build_json_empty():
    data = _build_json([], [], [], {})
    assert data == []


# ── _build_csv ───────────────────────────────────────────────────────


def test_build_csv_flattening():
    rows = _build_csv(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert len(rows) == 3  # 2 + 1 exemplars across 2 codes in 1 theme in 1 interp
    for row in rows:
        assert row["interpretation"] == "I1"
        assert row["theme"] == "T1"
    codes_in_rows = [r["code"] for r in rows]
    assert codes_in_rows.count("C1") == 2
    assert codes_in_rows.count("C2") == 1
    eids = [r["id"] for r in rows]
    assert "10" in eids
    assert "11" in eids
    assert "12" in eids


def test_build_csv_columns():
    rows = _build_csv(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    expected = CSV_COLUMNS
    assert list(rows[0].keys()) == expected


def test_build_csv_content():
    rows = _build_csv(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    row_for_10 = next(r for r in rows if r["id"] == "10")
    assert row_for_10["document"] == "doc1"
    assert row_for_10["tag"] == TAG
    assert row_for_10["content"] == "Exemplar ten content."
    assert row_for_10["keywords"] == "kw1, kw2"
    assert row_for_10["code"] == "C1"
    assert row_for_10["theme"] == "T1"
    assert row_for_10["interpretation"] == "I1"

    row_for_12 = next(r for r in rows if r["id"] == "12")
    assert row_for_12["document"] == "doc2"
    assert row_for_12["keywords"] == ""


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
    assert rows[0]["id"] == ""
    assert rows[0]["code"] == "C1"


# ── _build_markdown ──────────────────────────────────────────────────


def test_build_markdown_heading_hierarchy():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert "# I1" in md
    assert "Narrative: First interpretation" in md
    assert "## T1" in md
    assert "Description: First theme" in md
    assert "### C1" in md
    assert "Description: First code" in md
    assert "### C2" in md


def test_build_markdown_exemplar_content():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    assert "Exemplar ten content." in md
    assert "Exemplar twelve content." in md


def test_build_markdown_multi_line_content():
    md = _build_markdown(SAMPLE_INTERPS, SAMPLE_THEMES, SAMPLE_CODES, SAMPLE_EXEMPLARS)
    # Multi-line content is collapsed to single line in list items
    assert "Exemplar eleven multi-line content." in md


def test_build_markdown_empty():
    md = _build_markdown([], [], [], {})
    assert md.strip() == ""
