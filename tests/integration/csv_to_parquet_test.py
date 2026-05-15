"""End-to-end conversion using actual project data.

Tests that the converter works correctly with the real
data/raw/data.csv and data/raw/tags.csv files.
"""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

import polars as pl

# Add src/python to sys.path so persistence can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent / "src" / "python"),
)

from persistence.converter import convert_csvs


class TestCSVToParquetE2E(unittest.TestCase):
    """End-to-end tests for CSV to Parquet conversion."""

    def setUp(self) -> None:
        self.data_raw = Path("data/raw")
        self.data_processed = Path("data/processed")

    def test_convert_real_data(self) -> None:
        """Test conversion with actual project data."""
        stats = convert_csvs()

        # Check files exist
        exemplars_path = self.data_processed / "exemplars.parquet"
        tags_path = self.data_processed / "tags.parquet"
        self.assertTrue(exemplars_path.exists())
        self.assertTrue(tags_path.exists())

        # Verify exemplars row count
        exemplars = pl.scan_parquet(exemplars_path)
        csv_rows = (
            pl.scan_csv(self.data_raw / "data.csv").select(pl.len()).collect().item()
        )
        self.assertEqual(exemplars.select(pl.len()).collect().item(), csv_rows)

        # Verify tags row count
        tags_df = pl.scan_parquet(tags_path)
        tags_csv_rows = (
            pl.scan_csv(self.data_raw / "tags.csv").select(pl.len()).collect().item()
        )
        self.assertEqual(tags_df.select(pl.len()).collect().item(), tags_csv_rows)

        # Compression >= 50% for exemplars (small tags file may not compress as well)
        self.assertLess(stats["exemplars"]["compression_ratio"], 0.5)

        # Schema check for exemplars
        exemplars_schema = pl.scan_parquet(exemplars_path).schema
        self.assertIn("id", exemplars_schema)
        self.assertIn("content_hash", exemplars_schema)
        self.assertIn("keywords", exemplars_schema)

        # n_contents reconciled: compare with computed from data.csv
        tags_parquet = (
            pl.scan_parquet(tags_path)
            .with_columns(pl.col("tag").cast(pl.String))
            .collect()
        )
        exemplar_counts = (
            pl.scan_csv(self.data_raw / "data.csv")
            .group_by("tag")
            .len()
            .rename({"len": "expected_n"})
            .collect()
        )
        tags_check = tags_parquet.join(exemplar_counts, on="tag", how="left").fill_null(
            0
        )
        for row in tags_check.iter_rows(named=True):
            self.assertEqual(row["n_contents"], row["expected_n"])

    def test_parquet_readable_by_polars_scan(self) -> None:
        """Verify Parquet files are readable by scan_parquet."""
        convert_csvs()

        exemplars_path = self.data_processed / "exemplars.parquet"
        tags_path = self.data_processed / "tags.parquet"

        # scan_parquet should work without error
        ex_lf = pl.scan_parquet(exemplars_path)
        self.assertIsInstance(ex_lf, pl.LazyFrame)

        tags_lf = pl.scan_parquet(tags_path)
        self.assertIsInstance(tags_lf, pl.LazyFrame)

    def test_type_preservation(self) -> None:
        """Verify column types are preserved correctly."""
        convert_csvs()

        exemplars_path = self.data_processed / "exemplars.parquet"
        tags_path = self.data_processed / "tags.parquet"

        ex_df = pl.read_parquet(exemplars_path)
        self.assertEqual(ex_df["id"].dtype, pl.Int64)
        self.assertEqual(ex_df["document"].dtype, pl.String)
        self.assertEqual(ex_df["tag"].dtype, pl.Categorical)
        self.assertEqual(ex_df["content"].dtype, pl.String)
        self.assertEqual(ex_df["keywords"].dtype, pl.List(pl.String))
        self.assertEqual(ex_df["content_hash"].dtype, pl.String)

        tags_df = pl.read_parquet(tags_path)
        self.assertEqual(tags_df["tag"].dtype, pl.Categorical)
        self.assertEqual(tags_df["description"].dtype, pl.String)
        self.assertEqual(tags_df["n_contents"].dtype, pl.Int64)


if __name__ == "__main__":
    unittest.main()
