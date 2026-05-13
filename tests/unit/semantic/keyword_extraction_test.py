"""Tests for KeyBERT-based keyword extraction.

Covers:
- Successful extraction produces keywords.parquet with correct schema
- Immutability guard: existing file skips re-extraction
- force_rebuild=True overwrites existing file
- Empty exemplars produce empty keywords.parquet
- Short/empty content produces no keywords for that exemplar
"""

# flake8: noqa: E402
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import polars as pl
from persistence.loaders import clear_cache, configure_paths


def _make_exemplar_df(n: int, seed: int = 0) -> pl.LazyFrame:
    """Create a LazyFrame with n exemplars for testing."""
    import numpy as np

    rng = np.random.default_rng(seed)
    data = {
        "id": list(range(1, n + 1)),
        "document": [f"doc{i}" for i in range(1, n + 1)],
        "tag": ["test.tag"] * n,
        "content": [
            f"This is the content of exemplar {i}. It has some important terms like resilience and adaptation."
            for i in range(1, n + 1)
        ],
        "keywords": [[] for _ in range(n)],
        "content_hash": [f"ch_{i}_{rng.integers(0, 99999)}" for i in range(1, n + 1)],
        "keyword_count": [0] * n,
    }
    return pl.DataFrame(data).lazy()


class TestKeywordExtraction(unittest.TestCase):
    """Tests for extract_keywords with mocked KeyBERT."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.processed = self.tmpdir / "data" / "processed"
        self.processed.mkdir(parents=True, exist_ok=True)
        configure_paths(self.processed)
        clear_cache()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)
        clear_cache()

    # -- Successful extraction -------------------------------------------------

    @mock.patch("semantic.keyword_extraction.load_exemplars")
    @mock.patch("semantic.keyword_extraction.KeyBERT")
    def test_extracts_keywords(self, mock_keybert_cls, mock_load):
        """Three exemplars × 5 keywords = 15 keyword rows written."""
        mock_load.return_value = _make_exemplar_df(3, seed=1)

        # Mock KeyBERT instance
        mock_model = mock.MagicMock()
        mock_keybert_cls.return_value = mock_model
        mock_model.extract_keywords.return_value = [
            ("resilience", 0.85),
            ("adaptation", 0.72),
            ("mental health", 0.68),
            ("coping", 0.55),
            ("stress", 0.42),
        ]

        from semantic.keyword_extraction import extract_keywords

        result_lf = extract_keywords()
        df = result_lf.collect()

        self.assertEqual(df.height, 15)
        self.assertIn("keyword_id", df.columns)
        self.assertIn("exemplar_id", df.columns)
        self.assertIn("keyword_text", df.columns)
        self.assertIn("frequency", df.columns)
        # frequency is int32 with score*10000
        self.assertEqual(df["frequency"].dtype, pl.Int32)

    # -- Immutability guard ----------------------------------------------------

    @mock.patch("semantic.keyword_extraction.load_exemplars")
    @mock.patch("semantic.keyword_extraction.KeyBERT")
    def test_skip_when_exists(self, mock_keybert_cls, mock_load):
        """Existing keywords.parquet skips re-extraction."""
        # Pre-write a file
        existing = pl.DataFrame(
            {
                "keyword_id": [1],
                "exemplar_id": [1],
                "keyword_text": ["existing"],
                "frequency": [9999],
            },
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            },
        )
        existing.write_parquet(self.processed / "keywords.parquet")

        mock_load.return_value = _make_exemplar_df(3, seed=2)

        from semantic.keyword_extraction import extract_keywords

        result_lf = extract_keywords()
        df = result_lf.collect()

        # Should return the pre-existing data, not re-extract
        self.assertEqual(df.height, 1)
        self.assertEqual(df["keyword_text"][0], "existing")
        mock_keybert_cls.assert_not_called()

    # -- force_rebuild --------------------------------------------------------

    @mock.patch("semantic.keyword_extraction.load_exemplars")
    @mock.patch("semantic.keyword_extraction.KeyBERT")
    def test_force_rebuild_overwrites(self, mock_keybert_cls, mock_load):
        """force_rebuild=True overwrites existing keywords.parquet."""
        # Pre-write a file
        existing = pl.DataFrame(
            {
                "keyword_id": [1],
                "exemplar_id": [1],
                "keyword_text": ["existing"],
                "frequency": [9999],
            },
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            },
        )
        existing.write_parquet(self.processed / "keywords.parquet")

        mock_load.return_value = _make_exemplar_df(2, seed=3)

        mock_model = mock.MagicMock()
        mock_keybert_cls.return_value = mock_model
        mock_model.extract_keywords.return_value = [
            ("resilience", 0.85),
            ("adaptation", 0.72),
            ("mental health", 0.68),
            ("coping", 0.55),
            ("stress", 0.42),
        ]

        from semantic.keyword_extraction import extract_keywords

        result_lf = extract_keywords(force_rebuild=True)
        df = result_lf.collect()

        self.assertEqual(df.height, 10)  # 2 exemplars × 5
        mock_keybert_cls.assert_called_once()

    # -- Empty exemplars ------------------------------------------------------

    @mock.patch("semantic.keyword_extraction.load_exemplars")
    def test_empty_exemplars(self, mock_load):
        """No exemplars produces empty keywords.parquet."""
        empty = pl.DataFrame(
            schema={
                "id": pl.Int64,
                "document": pl.String,
                "tag": pl.String,
                "content": pl.String,
                "keywords": pl.List(pl.String),
                "content_hash": pl.String,
                "keyword_count": pl.Int64,
            }
        )
        mock_load.return_value = empty.lazy()

        from semantic.keyword_extraction import extract_keywords

        result_lf = extract_keywords()
        df = result_lf.collect()

        self.assertEqual(df.height, 0)

    # -- Short/empty content --------------------------------------------------

    @mock.patch("semantic.keyword_extraction.load_exemplars")
    @mock.patch("semantic.keyword_extraction.KeyBERT")
    def test_empty_content_skipped(self, mock_keybert_cls, mock_load):
        """Exemplar with empty content produces no keywords for that row."""
        df = pl.DataFrame(
            {
                "id": [1, 2],
                "document": ["d1", "d2"],
                "tag": ["t", "t"],
                "content": ["Some valid content with important terms.", ""],
                "keywords": [[], []],
                "content_hash": ["ch1", "ch2"],
                "keyword_count": [0, 0],
            }
        )
        mock_load.return_value = df.lazy()

        mock_model = mock.MagicMock()
        mock_keybert_cls.return_value = mock_model
        mock_model.extract_keywords.return_value = [
            ("resilience", 0.85),
            ("adaptation", 0.72),
            ("mental health", 0.68),
            ("coping", 0.55),
            ("stress", 0.42),
        ]

        from semantic.keyword_extraction import extract_keywords

        result_lf = extract_keywords()
        result_df = result_lf.collect()

        # Only exemplar 1 (valid content) should produce keywords
        self.assertEqual(result_df.height, 5)
        self.assertEqual(result_df["exemplar_id"].to_list(), [1] * 5)


if __name__ == "__main__":
    unittest.main()
