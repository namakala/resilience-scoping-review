"""Persistence layer: artifact loading, conversion, and state management."""

from .converter import CSVToParquetConverter, convert_csvs
from .duckdb_connection import get_connection, get_schema_version
from .duckdb_init import init_or_migrate, initialize_database
from .duckdb_migrations import migrate_schema
from .exceptions import ConversionError, DataQualityError, SchemaValidationError
from .loaders import clear_cache, load_exemplars, load_keywords, load_tags

__all__ = [
    # Converter API
    "CSVToParquetConverter",
    "convert_csvs",
    # DuckDB initialization API
    "get_connection",
    "initialize_database",
    "get_schema_version",
    "migrate_schema",
    "init_or_migrate",
    # Loader API
    "load_exemplars",
    "load_tags",
    "load_keywords",
    "clear_cache",
    # Exceptions
    "ConversionError",
    "SchemaValidationError",
    "DataQualityError",
]
