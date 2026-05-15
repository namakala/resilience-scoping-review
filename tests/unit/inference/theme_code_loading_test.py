"""Unit tests for inference/theme_code_loading.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import duckdb  # noqa: E402
from inference.theme_code_loading import (  # noqa: E402
    _CodeRow,
    load_approved_codes,
    load_approved_codes_grouped,
)


class TestLoadApprovedCodes(unittest.TestCase):
    """load_approved_codes: fetch and filter approved code nodes."""

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_filters_approved_only(self, mock_get):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "A",
                "definition": "def A",
                "status": "approved",
                "data_json": {"exemplar_ids": ["e1"]},
            },
            {
                "id": 2,
                "name": "B",
                "definition": "def B",
                "status": "draft",
                "data_json": None,
            },
            {
                "id": 3,
                "name": "C",
                "definition": "def C",
                "status": "approved",
                "data_json": None,
            },
        ]
        result = load_approved_codes("T1")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, 1)
        self.assertEqual(result[0].name, "A")
        self.assertEqual(result[0].definition, "def A")
        self.assertEqual(result[0].exemplar_count, 1)
        self.assertEqual(result[1].id, 3)
        self.assertEqual(result[1].name, "C")
        self.assertEqual(result[1].exemplar_count, 0)

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_empty_when_no_approved(self, mock_get):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "A",
                "definition": "def",
                "status": "draft",
                "data_json": None,
            },
        ]
        result = load_approved_codes("T1")
        self.assertEqual(result, [])

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_empty_when_no_nodes(self, mock_get):
        mock_get.return_value = []
        result = load_approved_codes("T1")
        self.assertEqual(result, [])

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_handles_missing_data_json(self, mock_get):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "A",
                "definition": "def",
                "status": "approved",
                "data_json": None,
            },
        ]
        result = load_approved_codes("T1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].exemplar_count, 0)

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_handles_non_dict_data_json(self, mock_get):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "A",
                "definition": "def",
                "status": "approved",
                "data_json": "string",
            },
        ]
        result = load_approved_codes("T1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].exemplar_count, 0)

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_sorts_by_id(self, mock_get):
        mock_get.return_value = [
            {
                "id": 3,
                "name": "C",
                "definition": "def",
                "status": "approved",
                "data_json": None,
            },
            {
                "id": 1,
                "name": "A",
                "definition": "def",
                "status": "approved",
                "data_json": None,
            },
        ]
        result = load_approved_codes("T1")
        self.assertEqual([r.id for r in result], [1, 3])


class TestLoadApprovedCodesGrouped(unittest.TestCase):
    """load_approved_codes_grouped: single-tag vs multi-tag discovery."""

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_single_tag_returns_grouped(self, mock_get):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "A",
                "definition": "def",
                "status": "approved",
                "data_json": {"exemplar_ids": ["e1"]},
            },
        ]
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = load_approved_codes_grouped(con, tag="T1")
        self.assertIn("T1", result)
        self.assertEqual(len(result["T1"]), 1)
        self.assertEqual(result["T1"][0].name, "A")

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_single_tag_empty_returns_empty(self, mock_get):
        mock_get.return_value = []
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = load_approved_codes_grouped(con, tag="T1")
        self.assertEqual(result, {})

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_discover_tags(self, mock_get):
        def fake_get_nodes(type_, tag):
            if tag == "T1":
                return [
                    {
                        "id": 1,
                        "name": "A",
                        "definition": "def",
                        "status": "approved",
                        "data_json": None,
                    },
                ]
            elif tag == "T2":
                return [
                    {
                        "id": 2,
                        "name": "B",
                        "definition": "def",
                        "status": "approved",
                        "data_json": None,
                    },
                ]
            return []

        mock_get.side_effect = fake_get_nodes

        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        con.execute.return_value.fetchall.return_value = [("T1",), ("T2",)]
        result = load_approved_codes_grouped(con, tag=None)
        self.assertIn("T1", result)
        self.assertIn("T2", result)
        self.assertEqual(len(result), 2)

    @patch("inference.theme_code_loading.get_nodes_by_type_and_tag")
    def test_discover_no_tags(self, mock_get):
        mock_get.return_value = []
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        con.execute.return_value.fetchall.return_value = []
        result = load_approved_codes_grouped(con, tag=None)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
