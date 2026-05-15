"""Tests for inference/tag_context.py — tag metadata fetching."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.tag_context import get_tag_metadata  # noqa: E402


class TestGetTagMetadata(unittest.TestCase):
    """get_tag_metadata: fetch description and ontology path."""

    @patch("inference.tag_context.load_tags")
    @patch("inference.tag_context.get_ancestors")
    def test_returns_description_and_path(self, mock_anc, mock_load_tags):
        mock_anc.return_value = ["root", "p"]
        mock_lf = MagicMock()
        mock_lf.filter.return_value = mock_lf
        mock_lf.select.return_value = mock_lf
        mock_df = MagicMock()
        mock_df.is_empty.return_value = False
        mock_df.__getitem__.return_value = ["Tag description"]
        mock_lf.collect.return_value = mock_df
        mock_load_tags.return_value = mock_lf

        desc, path = get_tag_metadata("root.p.T")
        self.assertEqual(desc, "Tag description")
        self.assertEqual(path, ["root", "p", "root.p.T"])

    @patch("inference.tag_context.load_tags")
    @patch("inference.tag_context.get_ancestors")
    def test_raises_if_tag_missing(self, mock_anc, mock_load_tags):
        mock_lf = MagicMock()
        mock_lf.filter.return_value = mock_lf
        mock_lf.select.return_value = mock_lf
        mock_df = MagicMock()
        mock_df.is_empty.return_value = True
        mock_lf.collect.return_value = mock_df
        mock_load_tags.return_value = mock_lf

        with self.assertRaises(KeyError):
            get_tag_metadata("missing")


if __name__ == "__main__":
    unittest.main()
