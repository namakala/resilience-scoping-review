"""Unit tests for inference/interpretation_span_processor.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.batching import Batch  # noqa: E402
from inference.interpretation_span_processor import (  # noqa: E402
    _InterpretationSpanItem,
    _process_interpretation_span,
)
from inference.parsing import InterpretationInference
from inference.theme_loading_for_interpretation import _ThemeRow


def _make_theme_row(id_, tag, name="T", narrative="n", code_ids=None):
    return _ThemeRow(
        id=id_,
        tag=tag,
        theme_name=name,
        narrative=narrative,
        code_ids=code_ids or ["C1", "C2"],
    )


def _make_span_batch(
    tags=("A", "B"),
    themes_by_tag=None,
):
    """Helper: create a Batch with one _InterpretationSpanItem."""
    if themes_by_tag is None:
        themes_by_tag = {
            "A": [_make_theme_row(1, "A")],
            "B": [_make_theme_row(2, "B")],
        }
    item = _InterpretationSpanItem(
        tag="A",
        id="interp_span_00",
        span_tags=tags,
        themes_by_tag=themes_by_tag,
    )
    return Batch(
        tag="A",
        items=[item],
        batch_index=0,
        total_batches=1,
    )


class TestProcessInterpretationSpan(unittest.TestCase):
    """_process_interpretation_span: render, infer, parse, post-process."""

    def setUp(self):
        from inference.tracking import reset_tracker

        reset_tracker()

    @patch("inference.interpretation_span_processor.infer_batch_with_retry")
    @patch("inference.interpretation_span_processor.parse_interpretation_response")
    @patch("inference.interpretation_span_processor.build_tag_hierarchy")
    @patch("inference.interpretation_span_processor.build_ontology_subtree")
    @patch("inference.interpretation_span_processor.mark_success")
    @patch("inference.interpretation_span_processor.load_fewshot")
    def test_happy_path(
        self,
        mock_fewshot,
        mock_mark_success,
        mock_subtree,
        mock_hierarchy,
        mock_parse,
        mock_infer,
    ):
        con = MagicMock()
        tracker = MagicMock()
        batch = _make_span_batch()

        mock_fewshot.return_value = None
        mock_hierarchy.return_value = [["A", "A.B"]]
        mock_subtree.return_value = "A\n  A.B"

        resp = MagicMock()
        resp.usage = None
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"interpretations": []}'
        mock_infer.return_value = [resp]

        mock_parse.return_value = [
            InterpretationInference(
                interpretation_name="CrossCutting",
                narrative="Synthesis narrative",
                theme_ids=["1", "2"],
                key_insights=["Key insight"],
            )
        ]

        result = _process_interpretation_span(con, batch, tracker)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].interpretation_name, "CrossCutting")
        self.assertEqual(result[0].theme_ids, ["1", "2"])
        mock_mark_success.assert_any_call(con, 1, "theme", "interpretation")
        mock_mark_success.assert_any_call(con, 2, "theme", "interpretation")

    @patch("inference.interpretation_span_processor.infer_batch_with_retry")
    @patch("inference.interpretation_span_processor.parse_interpretation_response")
    @patch("inference.interpretation_span_processor.build_tag_hierarchy")
    @patch("inference.interpretation_span_processor.build_ontology_subtree")
    @patch("inference.interpretation_span_processor.mark_success")
    @patch("inference.interpretation_span_processor.load_fewshot")
    def test_llm_returns_empty_interpretations(
        self,
        mock_fewshot,
        mock_mark_success,
        mock_subtree,
        mock_hierarchy,
        mock_parse,
        mock_infer,
    ):
        con = MagicMock()
        tracker = MagicMock()
        batch = _make_span_batch()

        mock_fewshot.return_value = None
        mock_hierarchy.return_value = [["A", "A.B"]]
        mock_subtree.return_value = "A\n  A.B"
        resp = MagicMock()
        resp.usage = None
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"interpretations": []}'
        mock_infer.return_value = [resp]
        mock_parse.return_value = []

        result = _process_interpretation_span(con, batch, tracker)

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
