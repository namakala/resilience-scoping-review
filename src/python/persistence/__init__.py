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
from .state import (
    DEFAULT_STATE,
    get_dirty_flags,
    increment_user_action_count,
    load_state,
    reset_state,
    save_state,
    set_config_version,
    set_current_stage,
    set_last_checkpoint,
    update_dirty_flag,
    validate_state,
)

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
    # State management API
    "load_state",
    "save_state",
    "reset_state",
    "validate_state",
    "update_dirty_flag",
    "get_dirty_flags",
    "set_current_stage",
    "increment_user_action_count",
    "set_config_version",
    "set_last_checkpoint",
    "DEFAULT_STATE",
    # Exceptions
    "ConversionError",
    "SchemaValidationError",
    "DataQualityError",
]
