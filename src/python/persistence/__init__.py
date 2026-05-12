"""Persistence layer: artifact loading, conversion, and state management."""

from .cache_analytics import get_cache_stats
from .converter import CSVToParquetConverter, convert_csvs
from .duckdb_connection import get_connection, get_schema_version
from .duckdb_init import init_or_migrate, initialize_database
from .duckdb_migrations import migrate_schema
from .embedding_cache import (
    get_embedding,
    invalidate_by_content_hash,
    invalidate_entity,
    put_embedding,
)
from .exceptions import ConversionError, DataQualityError, SchemaValidationError
from .hash_utils import compute_model_hash
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
    # Embedding cache API
    "compute_model_hash",
    "get_embedding",
    "put_embedding",
    "invalidate_entity",
    "invalidate_by_content_hash",
    "get_cache_stats",
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
