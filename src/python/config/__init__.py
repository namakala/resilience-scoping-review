"""Application configuration, loaded from environment variables.

Usage:
    from config import groq_api_key, groq_model, batch_size

    api_key = groq_api_key()
    model = groq_model()
"""

from .settings import (
    batch_size,
    bm25_tokenizer_config,
    data_path,
    embedding_model,
    groq_api_key,
    groq_max_retries,
    groq_model,
    groq_timeout,
    log_level,
    model_cache_dir,
    processed_data_path,
    tags_path,
)

__all__ = [
    "groq_api_key",
    "groq_model",
    "groq_timeout",
    "groq_max_retries",
    "batch_size",
    "embedding_model",
    "model_cache_dir",
    "log_level",
    "data_path",
    "tags_path",
    "processed_data_path",
    "bm25_tokenizer_config",
]
