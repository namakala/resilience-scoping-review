"""Parquet writer with statistics and compression reporting.

Provides utilities to write Polars LazyFrames to Parquet format
and compute compression ratios, row counts, and file size metrics.
"""

from pathlib import Path
from typing import Any, Dict

import polars as pl


def write_parquet(
    lf: pl.LazyFrame,
    output_path: Path,
    input_size: int,
    logger=None,
) -> Dict[str, Any]:
    """Write a LazyFrame to Parquet and return conversion statistics.

    Args:
        lf: Polars LazyFrame to write
        output_path: Destination Parquet file path
        input_size: Size in bytes of the source file (e.g., original CSV)
        logger: Optional logger instance for info logging

    Returns:
        Dictionary with keys:
            - input_rows: number of rows in the LazyFrame
            - output_rows: number of rows written (verified by re-reading)
            - input_bytes: size of source file in bytes
            - output_bytes: size of written Parquet file
            - compression_ratio: output_size / input_size (0-1, lower is better)
    """
    if logger:
        logger.info("Writing Parquet", extra={"output": str(output_path)})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lf.sink_parquet(output_path)

    output_size = output_path.stat().st_size

    # Verify output row count
    output_rows = pl.scan_parquet(output_path).select(pl.len()).collect().item()
    input_rows = lf.select(pl.len()).collect().item()

    ratio = output_size / input_size if input_size > 0 else 0.0

    stats: Dict[str, Any] = {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "input_bytes": input_size,
        "output_bytes": output_size,
        "compression_ratio": round(ratio, 3),
    }

    if logger:
        logger.info("Parquet conversion stats", extra=stats)

    return stats
