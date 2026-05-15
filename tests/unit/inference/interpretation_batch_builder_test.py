"""Unit tests for inference/interpretation_batch_builder.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.interpretation_batch_builder import (  # noqa: E402
    build_interpretation_batches,
)
from inference.interpretation_span_processor import (  # noqa: E402
    _InterpretationSpanItem,
)
from inference.theme_loading_for_interpretation import _ThemeRow  # noqa: E402


def _make_theme_row(id_, tag, name="T", narrative="n", code_ids=None):
    return _ThemeRow(
        id=id_,
        tag=tag,
        theme_name=name,
        narrative=narrative,
        code_ids=code_ids or ["C1", "C2"],
    )


class TestBuildInterpretationBatches(unittest.TestCase):
    """build_interpretation_batches: convert tag sets to Batch objects."""

    @patch("inference.interpretation_batch_builder.load_approved_themes_grouped")
    def test_valid_span_creates_one_batch(self, mock_load):
        mock_load.return_value = {
            "A": [_make_theme_row(1, "A")],
            "B": [_make_theme_row(2, "B")],
        }
        spans = [{"A", "B"}]
        batches = build_interpretation_batches(spans)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].item_count, 1)
        self.assertIsInstance(batches[0].items[0], _InterpretationSpanItem)
        self.assertEqual(batches[0].items[0].span_tags, ("A", "B"))

    @patch("inference.interpretation_batch_builder.load_approved_themes_grouped")
    def test_span_with_no_themes_skipped(self, mock_load):
        mock_load.return_value = {}
        batches = build_interpretation_batches([{"A", "B"}])
        self.assertEqual(batches, [])

    @patch("inference.interpretation_batch_builder.load_approved_themes_grouped")
    def test_mixed_spans(self, mock_load):
        def side_effect(tags):
            if tags == {"A", "B"}:
                return {"A": [_make_theme_row(1, "A")]}
            return {}

        mock_load.side_effect = side_effect
        batches = build_interpretation_batches([{"A", "B"}, {"C", "D"}])
        self.assertEqual(len(batches), 1)


if __name__ == "__main__":
    unittest.main()
