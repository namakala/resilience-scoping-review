"""CSV reader with schema validation, data quality checks, and enrichment.

Functions to read raw CSV artifacts, validate required columns, detect
missing values, enrich exemplars with content hashes and empty keywords,
and reconcile tag counts from the source exemplars data.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import polars as pl
from utils.logging import get_logger

from .exceptions import ConversionError, DataQualityError, SchemaValidationError

EXEMPLARS_REQUIRED_COLS = {"id", "document", "tag", "content"}
TAGS_REQUIRED_COLS = {"tag", "description", "n_contents"}


def _validate_schema(
    lf: pl.LazyFrame,
    required_cols: set,
    logger: logging.Logger,
    subject: str,
    error_type,
) -> None:
    """Validate that LazyFrame schema contains required columns."""
    cols = set(lf.collect_schema().names())
    missing = required_cols - cols
    if missing:
        msg = f"{subject} missing required columns: {missing}"
        logger.error(msg, extra={"found": list(sorted(cols))})
        raise error_type(msg)


def _check_null_empty(
    lf: pl.LazyFrame, col_name: str, logger: logging.Logger
) -> tuple[int, int]:
    """Return (null_count, empty_count) for a given column."""
    null_count = lf.filter(pl.col(col_name).is_null()).select(pl.len()).collect().item()
    empty_count = (
        lf.filter(pl.col(col_name).cast(pl.String).str.strip_chars() == "")
        .select(pl.len())
        .collect()
        .item()
    )
    return null_count, empty_count


def read_and_enrich_exemplars(
    csv_path: Path, logger: Optional[logging.Logger] = None
) -> pl.LazyFrame:
    """Read exemplars CSV, validate schema, check quality, and enrich.

    Enrichment adds:
        - content_hash: first 16 hex chars of SHA256(content)
        - keywords: empty list (nullable placeholder for future extraction)

    Args:
        csv_path: Path to data/raw/data.csv
        logger: Optional logger instance (created if None)

    Returns:
        Polars LazyFrame with enriched columns and typed schema

    Raises:
        ConversionError: If file not found
        SchemaValidationError: If required columns missing
        DataQualityError: If nulls/empty strings in id or content
    """
    logger = logger or get_logger(__name__)
    logger.info("Reading exemplars CSV", extra={"path": str(csv_path)})

    if not csv_path.exists():
        raise ConversionError(f"Exemplars CSV not found: {csv_path}")

    lf = pl.scan_csv(csv_path)

    # Schema validation
    _validate_schema(
        lf, EXEMPLARS_REQUIRED_COLS, logger, "Exemplars", SchemaValidationError
    )

    # Data quality: nulls and empty strings in id and content
    id_null, id_empty = _check_null_empty(lf, "id", logger)
    content_null, content_empty = _check_null_empty(lf, "content", logger)

    total_bad = id_null + id_empty + content_null + content_empty
    if total_bad > 0:
        details = {
            "id_null": id_null,
            "content_null": content_null,
            "id_empty": id_empty,
            "content_empty": content_empty,
        }
        logger.error("Data quality violations", extra=details)
        raise DataQualityError(
            f"Exemplars contain missing values in id/content: {details}"
        )

    # Enrichment: content_hash and keywords
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

    input_rows = enriched_lf.select(pl.len()).collect().item()
    logger.info("Exemplars enriched", extra={"rows": input_rows})
    return enriched_lf


def read_and_validate_tags(
    tags_csv: Path, exemplars_csv: Path, logger: Optional[logging.Logger] = None
) -> pl.LazyFrame:
    """Read tags CSV, validate schema, and reconcile n_contents from exemplars.

    Reconciliation: computes actual tag counts from data.csv and overwrites
    the n_contents column. If reconciliation fails, falls back to source values
    with a warning.

    Args:
        tags_csv: Path to data/raw/tags.csv
        exemplars_csv: Path to data/raw/data.csv (for count reconciliation)
        logger: Optional logger instance (created if None)

    Returns:
        Polars LazyFrame with typed schema (tag categorical, description string,
        n_contents int64)

    Raises:
        ConversionError: If tags CSV not found
        SchemaValidationError: If required columns missing
    """
    logger = logger or get_logger(__name__)
    logger.info("Reading tags CSV", extra={"path": str(tags_csv)})

    if not tags_csv.exists():
        raise ConversionError(f"Tags CSV not found: {tags_csv}")

    lf = pl.scan_csv(tags_csv)

    # Schema validation
    _validate_schema(lf, TAGS_REQUIRED_COLS, logger, "Tags", SchemaValidationError)

    # Collect to memory for reconciliation
    tags_df = lf.collect()

    try:
        exemplars_df = pl.scan_csv(exemplars_csv).select(["tag"]).collect()
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
        logger.warning(
            "Could not reconcile n_contents from exemplars; using source values",
            extra={"error": str(e)},
        )
        tags_df = tags_df.with_columns(
            [
                pl.col("n_contents").cast(pl.Int64),
                pl.col("description").cast(pl.String),
                pl.col("tag").cast(pl.Categorical).sort(),
            ]
        )

    logger.info("Tags validated and reconciled", extra={"rows": tags_df.height})
    return tags_df.lazy()
