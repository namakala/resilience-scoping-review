"""Comprehensive unit tests for the CSV to Parquet converter.

Covers:
- Successful conversion of exemplars and tags
- Schema validation (missing columns)
- Data quality validation (nulls and empty strings in id/content)
- Tag n_contents reconciliation from exemplars
- Type preservation and enrichment (categorical, content_hash, keywords)
"""

# flake8: noqa: E402
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add src/python to sys.path so persistence can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import polars as pl
from persistence.converter import (
    CSVToParquetConverter,
    DataQualityError,
    SchemaValidationError,
)


class TestCSVToParquetConverter(unittest.TestCase):
    """Tests for CSVToParquetConverter."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.fixtures_dir = Path(__file__).parent.parent.parent / "fixtures" / "csv"

        # Paths for converter
        self.exemplars_csv = self.tmpdir / "test_exemplars.csv"
        self.tags_csv = self.tmpdir / "test_tags.csv"
        self.exemplars_parquet = self.tmpdir / "test_exemplars.parquet"
        self.tags_parquet = self.tmpdir / "test_tags.parquet"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_convert_success(self) -> None:
        """Test successful conversion with valid data."""
        # 1. Prepare valid CSVs
        valid_exemplars = self.fixtures_dir / "valid_exemplars.csv"
        valid_tags = self.fixtures_dir / "valid_tags.csv"

        # Use existing fixtures
        import shutil

        shutil.copy(valid_exemplars, self.exemplars_csv)
        shutil.copy(valid_tags, self.tags_csv)

        converter = CSVToParquetConverter(
            self.exemplars_csv,
            self.tags_csv,
            self.exemplars_parquet,
            self.tags_parquet,
        )

        stats = converter.convert()

        # 2. Verify statistics
        self.assertEqual(stats["exemplars"]["output_rows"], 3)
        self.assertEqual(stats["tags"]["output_rows"], 2)
        self.assertGreater(stats["exemplars"]["compression_ratio"], 0.0)

        # 3. Verify Parquet content
        ex_df = pl.read_parquet(self.exemplars_parquet)
        self.assertEqual(ex_df.height, 3)
        self.assertEqual(ex_df["id"][0], 1)
        self.assertEqual(ex_df["tag"].dtype, pl.Categorical)
        self.assertIn("content_hash", ex_df.columns)
        self.assertIn("keywords", ex_df.columns)
        # Check hash (first 16 chars)
        expected_hash = hashlib.sha256(b"content1").hexdigest()[:16]
        self.assertEqual(ex_df["content_hash"][0], expected_hash)
        # Check empty keywords list
        self.assertEqual(ex_df["keywords"][0].to_list(), [])

        tag_df = pl.read_parquet(self.tags_parquet)
        self.assertEqual(tag_df.height, 2)
        # Verify reconciliation (tag1 should have 2 from data.csv)
        tag1_row = tag_df.filter(pl.col("tag") == "tag1")
        self.assertEqual(tag1_row["n_contents"][0], 2)

    def test_schema_validation_missing_cols(self) -> None:
        """Test that missing columns raise SchemaValidationError."""
        missing_cols_csv = self.fixtures_dir / "missing_cols_exemplars.csv"
        import shutil

        shutil.copy(missing_cols_csv, self.exemplars_csv)
        # create a dummy valid tags csv
        shutil.copy(self.fixtures_dir / "valid_tags.csv", self.tags_csv)

        converter = CSVToParquetConverter(
            self.exemplars_csv,
            self.tags_csv,
            self.exemplars_parquet,
            self.tags_parquet,
        )

        with self.assertRaisesRegex(SchemaValidationError, "missing required columns"):
            converter.convert()

    def test_data_quality_null_id(self) -> None:
        """Test that null IDs raise DataQualityError."""
        null_id_csv = self.fixtures_dir / "null_id_exemplars.csv"
        import shutil

        shutil.copy(null_id_csv, self.exemplars_csv)
        shutil.copy(self.fixtures_dir / "valid_tags.csv", self.tags_csv)

        converter = CSVToParquetConverter(
            self.exemplars_csv,
            self.tags_csv,
            self.exemplars_parquet,
            self.tags_parquet,
        )

        with self.assertRaisesRegex(DataQualityError, "missing values in id/content"):
            converter.convert()

    def test_data_quality_empty_content(self) -> None:
        """Test that empty content strings raise DataQualityError."""
        empty_content_csv = self.fixtures_dir / "empty_content_exemplars.csv"
        import shutil

        shutil.copy(empty_content_csv, self.exemplars_csv)
        shutil.copy(self.fixtures_dir / "valid_tags.csv", self.tags_csv)

        converter = CSVToParquetConverter(
            self.exemplars_csv,
            self.tags_csv,
            self.exemplars_parquet,
            self.tags_parquet,
        )

        with self.assertRaisesRegex(DataQualityError, "missing values in id/content"):
            converter.convert()

    def test_tags_reconciliation(self) -> None:
        """Test that tags n_contents are corrected from data.csv truth."""
        import shutil

        shutil.copy(self.fixtures_dir / "valid_exemplars.csv", self.exemplars_csv)
        # tags.csv has 100 for tag1, but valid_exemplars.csv only has 2
        shutil.copy(self.fixtures_dir / "n_content_mismatch_tags.csv", self.tags_csv)

        converter = CSVToParquetConverter(
            self.exemplars_csv,
            self.tags_csv,
            self.exemplars_parquet,
            self.tags_parquet,
        )
        converter.convert()

        tag_df = pl.read_parquet(self.tags_parquet)
        tag1_row = tag_df.filter(pl.col("tag") == "tag1")
        self.assertEqual(tag1_row["n_contents"][0], 2)

        tag2_row = tag_df.filter(pl.col("tag") == "tag2")
        self.assertEqual(tag2_row["n_contents"][0], 1)
