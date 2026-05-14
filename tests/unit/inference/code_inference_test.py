"""Unit tests for inference/code_inference.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.batching import Batch
from inference.code_inference import (
    _ExemplarRow,
    _get_existing_codes_for_tag,
    _load_pending_exemplars,
    _prepare_exemplars_dict,
    infer_codes,
)
from inference.parsing import CodeInference
from inference.prompts import PromptBundle
from persistence.loaders import load_exemplars, load_tags


class TestExemplarRow(unittest.TestCase):
    """_ExemplarRow dataclass."""

    def test_create(self):
        row = _ExemplarRow(id=1, content="test", keywords=["a", "b"])
        self.assertEqual(row.id, 1)
        self.assertEqual(row.content, "test")
        self.assertEqual(row.keywords, ["a", "b"])


class TestLoadPendingExemplars(unittest.TestCase):
    """_load_pending_exemplars: fetch and filter pending exemplars."""

    @patch("inference.code_inference.get_pending_items")
    @patch("inference.code_inference.load_exemplars")
    def test_returns_empty_when_no_pending(self, mock_load, mock_pending):
        mock_pending.return_value = []
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = _load_pending_exemplars(con, tag=None)
        self.assertEqual(result, [])

    @patch("inference.code_inference.get_pending_items")
    @patch("inference.code_inference.load_exemplars")
    def test_filters_by_tag(self, mock_load, mock_pending):
        mock_pending.return_value = ["1", "2"]
        mock_lf = MagicMock()
        mock_lf.select.return_value = mock_lf
        mock_lf.filter.return_value = mock_lf
        mock_lf.sort.return_value = mock_lf
        mock_df = MagicMock()
        mock_df.is_empty.return_value = False
        mock_df.iter_rows.return_value = [
            {"id": 1, "content": "c1", "keywords": ["k1"]},
            {"id": 2, "content": "c2", "keywords": []},
        ]
        mock_lf.collect.return_value = mock_df
        mock_load.return_value = mock_lf

        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = _load_pending_exemplars(con, tag="T1")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, 1)
        self.assertEqual(result[0].keywords, ["k1"])
        self.assertEqual(result[1].keywords, [])


class TestGetExistingCodesForTag(unittest.TestCase):
    """_get_existing_codes_for_tag: fetch approved codes for tag."""

    @patch("inference.code_inference.get_nodes_by_type_and_tag")
    def test_filters_approved_only(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "A", "definition": "def A", "status": "approved"},
            {"id": 2, "name": "B", "definition": "def B", "status": "draft"},
            {"id": 3, "name": "C", "definition": "def C", "status": "approved"},
        ]
        result = _get_existing_codes_for_tag("T1")
        self.assertEqual(len(result), 2)
        names = {c["name"] for c in result}
        self.assertSetEqual(names, {"A", "C"})

    @patch("inference.code_inference.get_nodes_by_type_and_tag")
    def test_empty_when_no_approved(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "A", "definition": "def A", "status": "draft"}
        ]
        result = _get_existing_codes_for_tag("T1")
        self.assertEqual(result, [])


class TestPrepareExemplarsDict(unittest.TestCase):
    """_prepare_exemplars_dict: convert _ExemplarRow list to dict list."""

    def test_structure(self):
        items = [
            _ExemplarRow(id=1, content="c1", keywords=["a"]),
            _ExemplarRow(id=2, content="c2", keywords=[]),
        ]
        result = _prepare_exemplars_dict(items)
        expected = [
            {"id": 1, "content": "c1", "keywords": ["a"]},
            {"id": 2, "content": "c2", "keywords": []},
        ]
        self.assertEqual(result, expected)


class TestInferCodes(unittest.TestCase):
    """Integration-style tests for infer_codes()."""

    def setUp(self):
        # Avoid cross-test contamination of TokenTracker singleton
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.code_inference._load_pending_exemplars")
    @patch("inference.code_inference.group_by_tag")
    @patch("inference.code_inference.get_tag_metadata")
    @patch("inference.code_inference._get_existing_codes_for_tag")
    @patch("inference.code_inference.load_fewshot")
    @patch("inference.code_inference.render_code_prompt")
    @patch("inference.code_inference.infer_batch_with_retry")
    @patch("inference.code_inference.parse_code_response")
    @patch("inference.code_inference.mark_success")
    @patch("inference.code_inference.mark_failure")
    @patch("inference.code_inference.logger")
    def test_full_flow_success(
        self,
        mock_logger,
        mock_mark_failure,
        mock_mark_success,
        mock_parse,
        mock_infer,
        mock_render,
        mock_fewshot,
        mock_existing,
        mock_meta,
        mock_group,
        mock_load,
    ):
        """Happy path: one exemplar, one code generated, status updated."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        exemplar = _ExemplarRow(1, "content", ["kw"])
        mock_load.return_value = [exemplar]

        batch = MagicMock(spec=Batch)
        batch.tag = "T1"
        batch.batch_id = "code_T1_batch_00"
        batch.items = [exemplar]
        batch.item_count = 1
        mock_group.return_value = [batch]

        mock_meta.return_value = ("desc", ["root", "T1"])
        mock_existing.return_value = []
        mock_fewshot.return_value = None

        bundle = MagicMock(spec=PromptBundle)
        mock_render.return_value = bundle

        mock_response = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 50
        mock_response.usage = usage
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"codes": [{"exemplar_id": "1", "code_name": "C1", '
            '"definition": "def", "supporting_quote": "quote", '
            '"related_existing_codes": []}]}'
        )
        mock_infer.return_value = [mock_response]

        code = CodeInference(
            exemplar_id="1",
            code_name="C1",
            definition="def",
            supporting_quote="quote",
            related_existing_codes=[],
        )
        mock_parse.return_value = [code]

        result = infer_codes(con, tag=None)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code_name, "C1")
        mock_mark_success.assert_called_once_with(con, 1, "exemplar", "code")


class TestTokenTracking(unittest.TestCase):
    """Verify token usage is logged via tracker."""

    def setUp(self):
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.code_inference._load_pending_exemplars")
    @patch("inference.code_inference.group_by_tag")
    @patch("inference.code_inference.get_tag_metadata")
    @patch("inference.code_inference._get_existing_codes_for_tag")
    @patch("inference.code_inference.load_fewshot")
    @patch("inference.code_inference.render_code_prompt")
    @patch("inference.code_inference.infer_batch_with_retry")
    @patch("inference.code_inference.parse_code_response")
    @patch("inference.code_inference.mark_success")
    @patch("inference.code_inference.mark_failure")
    def test_token_usage_logged(
        self,
        mock_mark_failure,
        mock_mark_success,
        mock_parse,
        mock_infer,
        mock_render,
        mock_fewshot,
        mock_existing,
        mock_meta,
        mock_group,
        mock_load,
    ):
        """Token usage is recorded and cost appears in summary log."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_load.return_value = [_ExemplarRow(1, "c", [])]

        batch = MagicMock(spec=Batch)
        batch.tag = "T1"
        batch.batch_id = "code_T1_batch_00"
        batch.items = [_ExemplarRow(1, "c", [])]
        batch.item_count = 1
        mock_group.return_value = [batch]

        mock_meta.return_value = ("d", ["root", "T1"])
        mock_existing.return_value = []
        mock_fewshot.return_value = None
        bundle = MagicMock()
        mock_render.return_value = bundle

        resp = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 200
        usage.completion_tokens = 80
        resp.usage = usage
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"codes": []}'
        mock_infer.return_value = [resp]
        mock_parse.return_value = []

        with patch("inference.code_inference.logger") as mock_logger:
            infer_codes(con)
            cost_log_calls = [
                c for c in mock_logger.info.call_args_list if "cost" in str(c).lower()
            ]
            self.assertTrue(len(cost_log_calls) > 0)


if __name__ == "__main__":
    unittest.main()
