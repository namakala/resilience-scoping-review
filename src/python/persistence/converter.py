"""CSV to Parquet converter orchestration.

Thin orchestrator that delegates to reader and writer modules.
Validates schemas, enriches data, and writes compressed Parquet files.

Public API:
    CSVToParquetConverter — orchestrator class
    convert_csvs — convenience function for default paths

Re-exports from submodules:
    ConversionError, SchemaValidationError, DataQualityError
"""

from pathlib import Path
from typing import Any, Dict, Optional

from utils.logging import get_logger

# Re-export exceptions for backward compatibility
from .exceptions import ConversionError, DataQualityError, SchemaValidationError

# Import reader and writer functions
from .reader import read_and_enrich_exemplars, read_and_validate_tags
from .writer import write_parquet

__all__ = [
    "CSVToParquetConverter",
    "convert_csvs",
    "ConversionError",
    "SchemaValidationError",
    "DataQualityError",
]


class CSVToParquetConverter:
    """Orchestrates CSV to Parquet conversion using reader and writer modules.

    Responsibilities:
        - Coordinate reading, validation, enrichment, and writing
        - Track input file sizes for compression statistics
        - Provide a simple convert() method for end-to-end processing

    Args:
        exemplars_csv: Path to data/raw/data.csv
        tags_csv: Path to data/raw/tags.csv
        exemplars_parquet: Output path for exemplars.parquet
        tags_parquet: Output path for tags.parquet
    """

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

        # Read and enrich exemplars
        exemplars_lf = read_and_enrich_exemplars(self.exemplars_csv, self.logger)

        # Write exemplars Parquet (compute CSV size for compression ratio)
        exemplars_csv_size = self.exemplars_csv.stat().st_size
        stats["exemplars"] = write_parquet(
            exemplars_lf,
            self.exemplars_parquet,
            input_size=exemplars_csv_size,
            logger=self.logger,
        )

        # Read and validate tags
        tags_lf = read_and_validate_tags(self.tags_csv, self.exemplars_csv, self.logger)

        # Write tags Parquet
        tags_csv_size = self.tags_csv.stat().st_size
        stats["tags"] = write_parquet(
            tags_lf,
            self.tags_parquet,
            input_size=tags_csv_size,
            logger=self.logger,
        )

        self.logger.info("Conversion complete", extra={"stats": stats})
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
