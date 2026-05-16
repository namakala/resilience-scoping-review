"""Application configuration, loaded from environment variables.

Usage:
    from config import groq_api_key, default_model, batch_size

    api_key = groq_api_key()
    model = default_model()
"""

from .settings import (
    batch_size,
    bm25_tokenizer_config,
    code_model,
    code_temperature,
    data_path,
    default_model,
    embedding_model,
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
    groq_api_key,
    groq_max_retries,
    groq_timeout,
    interpretation_model,
    interpretation_temperature,
    log_level,
    max_stage_cost_usd,
    model_cache_dir,
    processed_data_path,
    tags_path,
    theme_model,
    theme_temperature,
    token_cost_input_per_million,
    token_cost_output_per_million,
)

__all__ = [
    "batch_size",
    "bm25_tokenizer_config",
    "code_model",
    "code_temperature",
    "data_path",
    "default_model",
    "embedding_model",
    "fewshot_enabled",
    "fewshot_count",
    "fewshot_shuffle",
    "groq_api_key",
    "groq_max_retries",
    "groq_timeout",
    "interpretation_model",
    "interpretation_temperature",
    "log_level",
    "max_stage_cost_usd",
    "model_cache_dir",
    "processed_data_path",
    "tags_path",
    "theme_model",
    "theme_temperature",
    "token_cost_input_per_million",
    "token_cost_output_per_million",
]
