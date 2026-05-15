"""Tests for orchestration/export.py — data gathering and orchestration."""

from __future__ import annotations

from unittest import mock

from orchestration.export import _gather_approved_nodes, _query_approved


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
