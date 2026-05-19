"""Tests for orchestration/export.py — data gathering and orchestration."""

from __future__ import annotations

from unittest import mock

from orchestration.export import (
    _enrich_interp_theme_ids,
    _enrich_theme_code_ids,
    _gather_approved_nodes,
    _query_approved,
)


def test_query_approved_empty():
    """No approved nodes returns empty list."""
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = []
    result = _query_approved(mock_con, "code")
    assert result == []


def test_gather_approved_nodes_empty():
    """All three node types empty."""
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = []
    codes, themes, interps = _gather_approved_nodes(mock_con)
    assert codes == []
    assert themes == []
    assert interps == []


def test_gather_approved_nodes_query_order():
    """Verify the SQL query filters by type and status."""
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = []
    _gather_approved_nodes(mock_con)
    calls = [c[0][0] for c in mock_con.execute.call_args_list]
    for sql in calls:
        assert "status = 'approved'" in sql
        assert "ORDER BY id" in sql


# ── _enrich_interp_theme_ids ─────────────────────────────────────────


def test_enrich_interp_theme_ids_populates_when_missing():
    """Spans edges fill in data_json.theme_ids when key is absent."""
    interps = [
        {"id": 1, "data_json": {"tag_spans": ["A"]}},
        {"id": 2, "data_json": {}},
    ]
    mock_con = mock.MagicMock()

    def fake_execute(sql, params=None):
        fake = mock.MagicMock()
        if params and params[0] == 1:
            fake.fetchall.return_value = [(10,), (20,)]
        elif params and params[0] == 2:
            fake.fetchall.return_value = [(30,)]
        else:
            fake.fetchall.return_value = []
        return fake

    mock_con.execute.side_effect = fake_execute
    _enrich_interp_theme_ids(mock_con, interps)

    assert interps[0]["data_json"]["theme_ids"] == [10, 20]
    assert interps[1]["data_json"]["theme_ids"] == [30]


def test_enrich_interp_theme_ids_skips_when_already_populated():
    """Interpretations with existing theme_ids are left untouched."""
    interps = [
        {"id": 1, "data_json": {"theme_ids": [99]}},
    ]
    mock_con = mock.MagicMock()
    _enrich_interp_theme_ids(mock_con, interps)
    mock_con.execute.assert_not_called()
    assert interps[0]["data_json"]["theme_ids"] == [99]


def test_enrich_interp_theme_ids_handles_empty_list():
    """Empty theme_ids list is also treated as missing and enriched."""
    interps = [
        {"id": 1, "data_json": {"theme_ids": []}},
    ]
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = [(10,), (20,)]
    _enrich_interp_theme_ids(mock_con, interps)
    assert interps[0]["data_json"]["theme_ids"] == [10, 20]


def test_enrich_interp_theme_ids_no_edges():
    """No spans edges found — data_json left unchanged."""
    interps = [
        {"id": 1, "data_json": {}},
    ]
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = []
    _enrich_interp_theme_ids(mock_con, interps)
    assert "theme_ids" not in interps[0]["data_json"]


def test_enrich_interp_theme_ids_no_data_json():
    """Interpretation with no data_json key — create and populate."""
    interps = [
        {"id": 1},
    ]
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = [(10,)]
    _enrich_interp_theme_ids(mock_con, interps)
    assert interps[0]["data_json"]["theme_ids"] == [10]


# ── _enrich_theme_code_ids ───────────────────────────────────────────


def test_enrich_theme_code_ids_populates_when_missing():
    """Composed-of edges fill in data_json.code_ids when key is absent."""
    themes = [
        {"id": 10, "data_json": {}},
    ]
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = [(100,), (200,)]
    _enrich_theme_code_ids(mock_con, themes)
    assert themes[0]["data_json"]["code_ids"] == [100, 200]


def test_enrich_theme_code_ids_skips_when_already_populated():
    """Themes with existing code_ids are left untouched."""
    themes = [
        {"id": 10, "data_json": {"code_ids": [99]}},
    ]
    mock_con = mock.MagicMock()
    _enrich_theme_code_ids(mock_con, themes)
    mock_con.execute.assert_not_called()
    assert themes[0]["data_json"]["code_ids"] == [99]


def test_enrich_theme_code_ids_no_edges():
    """No composed-of edges found — data_json left unchanged."""
    themes = [
        {"id": 10, "data_json": {}},
    ]
    mock_con = mock.MagicMock()
    mock_con.execute.return_value.fetchall.return_value = []
    _enrich_theme_code_ids(mock_con, themes)
    assert "code_ids" not in themes[0]["data_json"]
