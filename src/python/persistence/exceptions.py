"""Conversion-specific exceptions for CSV to Parquet transformation.

Provides a clear exception hierarchy for different failure modes:
schema mismatches, data quality violations, and general conversion errors.
"""


class ConversionError(Exception):
    """Base exception for conversion failures."""


class SchemaValidationError(ConversionError):
    """Raised when CSV schema does not match expected columns."""


class DataQualityError(ConversionError):
    """Raised when data violates quality constraints (nulls, empty strings)."""
