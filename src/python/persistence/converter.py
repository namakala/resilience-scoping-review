"""CSV to Parquet converter with schema validation and enrichment.

Reads raw CSV artifacts, validates schemas, computes derived columns,
and writes compressed Parquet files. Enriches exemplars with nullable
keywords and content_hash; reconciles tag counts from source truth.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import polars as pl
from utils.logging import get_logger


class ConversionError(Exception):
    """Base exception for conversion failures."""


class SchemaValidationError(ConversionError):
    """Raised when CSV schema does not match expected columns."""


class DataQualityError(ConversionError):
    """Raised when data violates quality constraints (nulls, empty strings)."""


class CSVToParquetConverter:
    """Converts raw CSV exemplars and tags to validated Parquet format.

    Responsibilities:
    - Validate required columns and types
    - Detect missing values (null, empty strings) in critical fields
    - Enrich exemplars with content_hash (SHA256) and empty keywords list
    - Reconcile tags n_contents from data.csv
    - Write compressed Parquet with categorical encoding
    - Report statistics (row counts, compression ratio)

    Args:
        exemplars_csv: Path to data/raw/data.csv
        tags_csv: Path to data/raw/tags.csv
        exemplars_parquet: Output path for exemplars.parquet
        tags_parquet: Output path for tags.parquet
    """

    EXEMPLARS_REQUIRED_COLS = {"id", "document", "tag", "content"}
    TAGS_REQUIRED_COLS = {"tag", "description", "n_contents"}

    def __init__(
        self,
        exemplars_csv: Path,
        tags_csv: Path,
        exemplars_parquet: Path,
        tags_parquet: Path,
    ) -> None:
        self.exemplars_csv = Path(exemplars_csv)
        self.tags_csv = Path(tags_csv)
        self.exemplars_parquet = Path(exemplars_parquet)
        self.tags_parquet = Path(tags_parquet)
        self.logger = get_logger(self.__class__.__name__)

    def convert(self) -> Dict[str, Dict[str, Any]]:
        """Run full conversion pipeline.

        Returns:
            Dictionary with conversion stats per artifact:
            {
                "exemplars": {"input_rows": int, "output_rows": int,
                              "input_bytes": int, "output_bytes": int,
                              "compression_ratio": float},
                "tags": {...}
            }

        Raises:
            SchemaValidationError: If required columns missing
            DataQualityError: If null/empty in id/content
            ConversionError: For I/O or other failures
        """
        stats: Dict[str, Dict[str, Any]] = {}

        exemplars_lf = self._read_and_validate_exemplars()
        stats["exemplars"] = self._write_exemplars_parquet(exemplars_lf)

        tags_lf = self._read_and_validate_tags()
        stats["tags"] = self._write_tags_parquet(tags_lf)

        self.logger.info("Conversion complete", extra={"stats": stats})
        return stats

    def _read_and_validate_exemplars(self) -> pl.LazyFrame:
        """Load exemplars CSV, validate schema, and check data quality.

        Returns:
            Polars LazyFrame with enriched columns: content_hash, keywords

        Raises:
            SchemaValidationError: Missing required columns
            DataQualityError: Nulls or empty strings in id/content
        """
        self.logger.info(
            "Reading exemplars CSV", extra={"path": str(self.exemplars_csv)}
        )

        if not self.exemplars_csv.exists():
            raise ConversionError(f"Exemplars CSV not found: {self.exemplars_csv}")

        lf = pl.scan_csv(self.exemplars_csv)

        # Schema validation
        cols = set(lf.collect_schema().names())
        missing = self.EXEMPLARS_REQUIRED_COLS - cols
        if missing:
            msg = f"Exemplars missing required columns: {missing}"
            self.logger.error(msg, extra={"found": list(sorted(cols))})
            raise SchemaValidationError(msg)

        # Data quality: detect nulls and empty strings in id/content
        id_null_count = (
            lf.filter(pl.col("id").is_null()).select(pl.len()).collect().item()
        )
        content_null_count = (
            lf.filter(pl.col("content").is_null()).select(pl.len()).collect().item()
        )
        id_empty_count = (
            lf.filter(pl.col("id").cast(pl.String).str.strip_chars() == "")
            .select(pl.len())
            .collect()
            .item()
        )
        content_empty_count = (
            lf.filter(pl.col("content").cast(pl.String).str.strip_chars() == "")
            .select(pl.len())
            .collect()
            .item()
        )

        total_bad = (
            id_null_count + content_null_count + id_empty_count + content_empty_count
        )
        if total_bad > 0:
            details = {
                "id_null": id_null_count,
                "content_null": content_null_count,
                "id_empty": id_empty_count,
                "content_empty": content_empty_count,
            }
            self.logger.error("Data quality violations", extra=details)
            raise DataQualityError(
                f"Exemplars contain missing values in id/content: {details}"
            )

        # Enrichment: content_hash and empty keywords (nullable for now)
        enriched_lf = lf.with_columns(
            [
                pl.col("id").cast(pl.Int64),
                pl.col("document").cast(pl.String),
                pl.col("tag").cast(pl.Categorical).sort(),
                pl.col("content").cast(pl.String),
                (
                    pl.col("content")
                    .cast(pl.String)
                    .map_elements(
                        lambda c: hashlib.sha256(c.encode()).hexdigest()[:16],
                        return_dtype=pl.String,
                    )
                ).alias("content_hash"),
                pl.lit([], dtype=pl.List(pl.String)).alias("keywords"),
            ]
        )

        return enriched_lf

    def _read_and_validate_tags(self) -> pl.LazyFrame:
        """Load tags CSV, validate schema, reconcile n_contents from data.csv.

        Returns:
            Polars LazyFrame with consistent types

        Raises:
            SchemaValidationError: Missing required columns
        """
        self.logger.info("Reading tags CSV", extra={"path": str(self.tags_csv)})

        if not self.tags_csv.exists():
            raise ConversionError(f"Tags CSV not found: {self.tags_csv}")

        lf = pl.scan_csv(self.tags_csv)

        # Schema validation
        cols = set(lf.collect_schema().names())
        missing = self.TAGS_REQUIRED_COLS - cols
        if missing:
            msg = f"Tags missing required columns: {missing}"
            self.logger.error(msg, extra={"found": list(sorted(cols))})
            raise SchemaValidationError(msg)

        # Read tags into memory to reconcile n_contents
        tags_df = lf.collect()

        try:
            exemplars_df = pl.scan_csv(self.exemplars_csv).select(["tag"]).collect()
            tag_counts = (
                exemplars_df.group_by("tag")
                .agg(pl.len().alias("count"))
                .rename({"count": "actual_n_contents"})
            )
            tags_df = (
                tags_df.join(tag_counts, on="tag", how="left")
                .fill_null(0)
                .with_columns(
                    [
                        pl.col("actual_n_contents").cast(pl.Int64).alias("n_contents"),
                        pl.col("description").cast(pl.String),
                        pl.col("tag").cast(pl.Categorical).sort(),
                    ]
                )
                .drop("actual_n_contents")
            )
        except Exception as e:
            self.logger.warning(
                "Could not reconcile n_contents from exemplars; " "using source values",
                extra={"error": str(e)},
            )
            tags_df = tags_df.with_columns(
                [
                    pl.col("n_contents").cast(pl.Int64),
                    pl.col("description").cast(pl.String),
                    pl.col("tag").cast(pl.Categorical).sort(),
                ]
            )

        return tags_df.lazy()

    def _write_exemplars_parquet(self, lf: pl.LazyFrame) -> Dict[str, Any]:
        """Sink exemplars LazyFrame to Parquet and compute stats.

        Args:
            lf: Enriched exemplars LazyFrame

        Returns:
            Stats dict with row counts, file sizes, compression ratio
        """
        input_size = self.exemplars_csv.stat().st_size
        output_path = self.exemplars_parquet
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Writing exemplars Parquet",
            extra={"output": str(output_path)},
        )
        lf.sink_parquet(output_path)

        output_size = output_path.stat().st_size
        ratio = output_size / input_size if input_size > 0 else 0.0

        out_lf = pl.scan_parquet(output_path)
        output_rows = out_lf.select(pl.len()).collect().item()

        stats: Dict[str, Any] = {
            "input_rows": lf.select(pl.len()).collect().item(),
            "output_rows": output_rows,
            "input_bytes": input_size,
            "output_bytes": output_size,
            "compression_ratio": round(ratio, 3),
        }
        self.logger.info("Exemplars conversion stats", extra=stats)
        return stats

    def _write_tags_parquet(self, lf: pl.LazyFrame) -> Dict[str, Any]:
        """Sink tags LazyFrame to Parquet and compute stats."""
        input_size = self.tags_csv.stat().st_size
        output_path = self.tags_parquet
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Writing tags Parquet",
            extra={"output": str(output_path)},
        )
        lf.sink_parquet(output_path)

        output_size = output_path.stat().st_size
        ratio = output_size / input_size if input_size > 0 else 0.0

        output_rows = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        stats: Dict[str, Any] = {
            "input_rows": lf.select(pl.len()).collect().item(),
            "output_rows": output_rows,
            "input_bytes": input_size,
            "output_bytes": output_size,
            "compression_ratio": round(ratio, 3),
        }
        self.logger.info("Tags conversion stats", extra=stats)
        return stats


def convert_csvs(
    exemplars_csv: Optional[Path] = None,
    tags_csv: Optional[Path] = None,
    exemplars_parquet: Optional[Path] = None,
    tags_parquet: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Convenience function to run conversion with default paths.

    Args:
        exemplars_csv: Override default data/raw/data.csv
        tags_csv: Override default data/raw/tags.csv
        exemplars_parquet: Override default data/processed/exemplars.parquet
        tags_parquet: Override default data/processed/tags.parquet

    Returns:
        Conversion stats dict
    """
    converter = CSVToParquetConverter(
        exemplars_csv=exemplars_csv or Path("data/raw/data.csv"),
        tags_csv=tags_csv or Path("data/raw/tags.csv"),
        exemplars_parquet=exemplars_parquet or Path("data/processed/exemplars.parquet"),
        tags_parquet=tags_parquet or Path("data/processed/tags.parquet"),
    )
    return converter.convert()
