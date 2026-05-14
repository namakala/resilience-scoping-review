"""Unit tests for inference/theme_inference.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import duckdb
from inference.batching import Batch
from inference.parsing import ThemeInference
from inference.prompts import PromptBundle
from inference.theme_code_loading import _CodeRow
from inference.theme_inference import (
    _codes_to_dicts,
    _process_theme_batch,
    infer_themes,
)


class TestCodesToDicts(unittest.TestCase):
    """_codes_to_dicts: convert _CodeRow list to template context dicts."""

    def test_basic_conversion(self):
        items = [
            _CodeRow(id=1, tag="T1", name="N1", definition="D1", exemplar_count=3),
            _CodeRow(id=2, tag="T1", name="N2", definition="D2", exemplar_count=0),
        ]
        result = _codes_to_dicts(items)
        expected = [
            {"id": "1", "name": "N1", "definition": "D1", "exemplar_count": 3},
            {"id": "2", "name": "N2", "definition": "D2", "exemplar_count": 0},
        ]
        self.assertEqual(result, expected)

    def test_empty_list(self):
        self.assertEqual(_codes_to_dicts([]), [])


class TestInferThemes(unittest.TestCase):
    """Integration-style tests for infer_themes()."""

    def setUp(self):
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.theme_inference.load_approved_codes_grouped")
    def test_empty_codes_returns_empty(self, mock_load):
        mock_load.return_value = {}
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = infer_themes(con, tag="T1")
        self.assertEqual(result, [])

    @patch("inference.theme_inference.load_approved_codes_grouped")
    @patch("inference.theme_inference.group_by_tag")
    @patch("inference.theme_inference.get_tag_metadata")
    @patch("inference.theme_inference.load_fewshot")
    @patch("inference.theme_inference.render_theme_prompt")
    @patch("inference.theme_inference.infer_batch_with_retry")
    @patch("inference.theme_inference.parse_theme_response")
    @patch("inference.theme_inference.mark_success")
    @patch("inference.theme_inference.mark_failure")
    @patch("inference.theme_inference.logger")
    def test_full_flow_success(
        self,
        mock_logger,
        mock_mark_failure,
        mock_mark_success,
        mock_parse,
        mock_infer,
        mock_render,
        mock_fewshot,
        mock_meta,
        mock_group,
        mock_load,
    ):
        """Happy path: two codes grouped into one theme."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        codes = [
            _CodeRow(id=1, tag="T1", name="C1", definition="d1", exemplar_count=1),
            _CodeRow(id=2, tag="T1", name="C2", definition="d2", exemplar_count=1),
        ]
        mock_load.return_value = {"T1": codes}

        batch = MagicMock(spec=Batch)
        batch.tag = "T1"
        batch.batch_id = "theme_T1_batch_00"
        batch.items = codes
        batch.item_count = 2
        mock_group.return_value = [batch]

        mock_meta.return_value = ("desc", ["root", "T1"])
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
            '{"themes": [{"theme_name": "Theme A", "narrative": "n", '
            '"code_ids": ["1", "2"]}]}'
        )
        mock_infer.return_value = [mock_response]

        theme = ThemeInference(theme_name="Theme A", narrative="n", code_ids=["1", "2"])
        mock_parse.return_value = [theme]

        result = infer_themes(con, tag="T1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].theme_name, "Theme A")
        self.assertEqual(result[0].code_ids, ["1", "2"])
        mock_mark_success.assert_any_call(con, 1, "code", "theme")
        mock_mark_success.assert_any_call(con, 2, "code", "theme")

    @patch("inference.theme_inference.load_approved_codes_grouped")
    @patch("inference.theme_inference.group_by_tag")
    @patch("inference.theme_inference.get_tag_metadata")
    @patch("inference.theme_inference.load_fewshot")
    @patch("inference.theme_inference.render_theme_prompt")
    @patch("inference.theme_inference.infer_batch_with_retry")
    @patch("inference.theme_inference.parse_theme_response")
    @patch("inference.theme_inference.mark_success")
    @patch("inference.theme_inference.mark_failure")
    def test_code_not_covered_by_llm(
        self,
        mock_mark_failure,
        mock_mark_success,
        mock_parse,
        mock_infer,
        mock_render,
        mock_fewshot,
        mock_meta,
        mock_group,
        mock_load,
    ):
        """When LLM misses a code, it gets mark_failure."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        codes = [
            _CodeRow(id=1, tag="T1", name="C1", definition="d1", exemplar_count=1),
            _CodeRow(id=2, tag="T1", name="C2", definition="d2", exemplar_count=1),
        ]
        mock_load.return_value = {"T1": codes}

        batch = MagicMock(spec=Batch)
        batch.tag = "T1"
        batch.batch_id = "theme_T1_batch_00"
        batch.items = codes
        batch.item_count = 2
        mock_group.return_value = [batch]

        mock_meta.return_value = ("d", ["root", "T1"])
        mock_fewshot.return_value = None
        bundle = MagicMock()
        mock_render.return_value = bundle

        resp = MagicMock()
        resp.usage = None
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = (
            '{"themes": [{"theme_name": "T", "narrative": "n", "code_ids": ["1"]}]}'
        )
        mock_infer.return_value = [resp]
        mock_parse.return_value = [
            ThemeInference(theme_name="T", narrative="n", code_ids=["1"])
        ]

        infer_themes(con, tag="T1")
        mock_mark_success.assert_called_once_with(con, 1, "code", "theme")
        mock_mark_failure.assert_called_once_with(
            con, 2, "Code not assigned to any theme by LLM"
        )


class TestTokenTracking(unittest.TestCase):
    """Verify token usage is recorded via tracker."""

    def setUp(self):
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.theme_inference.load_approved_codes_grouped")
    @patch("inference.theme_inference.group_by_tag")
    @patch("inference.theme_inference.get_tag_metadata")
    @patch("inference.theme_inference.load_fewshot")
    @patch("inference.theme_inference.render_theme_prompt")
    @patch("inference.theme_inference.infer_batch_with_retry")
    @patch("inference.theme_inference.parse_theme_response")
    @patch("inference.theme_inference.mark_success")
    @patch("inference.theme_inference.mark_failure")
    def test_token_usage_logged(
        self,
        mock_mark_failure,
        mock_mark_success,
        mock_parse,
        mock_infer,
        mock_render,
        mock_fewshot,
        mock_meta,
        mock_group,
        mock_load,
    ):
        """Token usage appears in the summary log output."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        codes = [_CodeRow(id=1, tag="T1", name="C", definition="d", exemplar_count=1)]
        mock_load.return_value = {"T1": codes}

        batch = MagicMock(spec=Batch)
        batch.tag = "T1"
        batch.batch_id = "theme_T1_batch_00"
        batch.items = codes
        batch.item_count = 1
        mock_group.return_value = [batch]

        mock_meta.return_value = ("d", ["root", "T1"])
        mock_fewshot.return_value = None
        bundle = MagicMock()
        mock_render.return_value = bundle

        resp = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 200
        usage.completion_tokens = 80
        resp.usage = usage
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"themes": []}'
        mock_infer.return_value = [resp]
        mock_parse.return_value = []

        with patch("inference.theme_inference.logger") as mock_logger:
            infer_themes(con)
            cost_log_calls = [
                c for c in mock_logger.info.call_args_list if "cost" in str(c).lower()
            ]
            self.assertTrue(len(cost_log_calls) > 0)


if __name__ == "__main__":
    unittest.main()
