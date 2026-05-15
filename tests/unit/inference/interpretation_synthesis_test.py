"""Unit tests for inference/interpretation_synthesis.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import duckdb  # noqa: E402
from inference.batching import Batch  # noqa: E402
from inference.interpretation_span_processor import (  # noqa: E402
    _InterpretationSpanItem,
)
from inference.interpretation_synthesis import synthesize_interpretations  # noqa: E402
from inference.parsing import InterpretationInference  # noqa: E402
from inference.theme_loading_for_interpretation import _ThemeRow  # noqa: E402


def _make_theme_row(id_, tag, name="T", narrative="n", code_ids=None):
    return _ThemeRow(
        id=id_,
        tag=tag,
        theme_name=name,
        narrative=narrative,
        code_ids=code_ids or ["C1", "C2"],
    )


class TestSynthesizeInterpretations(unittest.TestCase):
    """Integration-style tests for synthesize_interpretations()."""

    def setUp(self):
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.interpretation_synthesis.get_ready_tags")
    def test_no_ready_tags_returns_empty(self, mock_ready):
        mock_ready.return_value = []
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        result = synthesize_interpretations(con)
        self.assertEqual(result, [])

    @patch("inference.interpretation_synthesis.get_ready_tags")
    @patch("inference.interpretation_synthesis.group_ready_tags_into_spans")
    def test_no_multi_tag_spans_returns_empty(self, mock_group, mock_ready):
        mock_ready.return_value = ["A"]
        mock_group.return_value = [{"A", "B"}]
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        with patch(
            "inference.interpretation_synthesis.build_interpretation_batches",
            return_value=[],
        ):
            result = synthesize_interpretations(con)
        self.assertEqual(result, [])

    @patch("inference.interpretation_synthesis.get_ready_tags")
    @patch("inference.interpretation_synthesis.group_ready_tags_into_spans")
    @patch("inference.interpretation_synthesis.build_interpretation_batches")
    @patch("inference.interpretation_synthesis.run_batches")
    def test_full_flow_success(
        self,
        mock_run,
        mock_build,
        mock_group,
        mock_ready,
    ):
        """Happy path: two tags, one interpretation."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_ready.return_value = ["A", "B"]
        mock_group.return_value = [{"A", "B"}]
        mock_batch = MagicMock(spec=Batch)
        mock_batch.tag = "A"
        mock_batch.batch_id = "interp_A_batch_00"
        item = _InterpretationSpanItem(
            tag="A",
            id="interp_span_00",
            span_tags=("A", "B"),
            themes_by_tag={
                "A": [_make_theme_row(1, "A")],
                "B": [_make_theme_row(2, "B")],
            },
        )
        mock_batch.items = [item]
        mock_build.return_value = [mock_batch]
        mock_tracker = MagicMock()
        mock_tracker.stage_summary.return_value = {
            "input_tokens": 100,
            "output_tokens": 50,
        }
        mock_run.return_value = (
            [
                InterpretationInference(
                    interpretation_name="CrossCutting Insight",
                    narrative="Synthesis across tags",
                    theme_ids=["1", "2"],
                    key_insights=["Key finding"],
                )
            ],
            mock_tracker,
        )

        result = synthesize_interpretations(con)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].interpretation_name, "CrossCutting Insight")
        self.assertEqual(result[0].theme_ids, ["1", "2"])

    @patch("inference.interpretation_synthesis.get_ready_tags")
    @patch("inference.interpretation_synthesis.group_ready_tags_into_spans")
    @patch("inference.interpretation_synthesis.build_interpretation_batches")
    @patch("inference.interpretation_synthesis.run_batches")
    def test_llm_returns_empty_interpretations(
        self,
        mock_run,
        mock_build,
        mock_group,
        mock_ready,
    ):
        """LLM returns empty interpretations array."""
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_ready.return_value = ["A", "B"]
        mock_group.return_value = [{"A", "B"}]
        mock_batch = MagicMock(spec=Batch)
        mock_batch.tag = "A"
        mock_batch.batch_id = "interp_span_00"
        item = _InterpretationSpanItem(
            tag="A",
            id="interp_span_00",
            span_tags=("A", "B"),
            themes_by_tag={"A": [_make_theme_row(1, "A")]},
        )
        mock_batch.items = [item]
        mock_build.return_value = [mock_batch]
        mock_tracker = MagicMock()
        mock_tracker.stage_summary.return_value = {}
        mock_run.return_value = ([], mock_tracker)

        result = synthesize_interpretations(con)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
