"""Configuration dataclass bundling all environment settings for DAG injection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import settings


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of all application settings for DAG dependency injection.

    Created once at pipeline entry and passed via Hamilton's ``with_config()``
    so every node function receives a typed ``config: Config`` parameter.
    """

    # Groq / LLM
    groq_api_key: str
    groq_model: str
    groq_timeout: int
    groq_max_retries: int

    # Inference temperatures
    code_temperature: float
    theme_temperature: float
    interpretation_temperature: float

    # Embedding model
    embedding_model: str
    model_cache_dir: Path

    # Processing
    batch_size: int
    log_level: str

    # Paths
    data_path: Path
    tags_path: Path
    processed_data_path: Path

    # BM25
    bm25_tokenizer_config: str

    # Few-shot
    fewshot_enabled: bool
    fewshot_count: int
    fewshot_shuffle: bool

    # Token tracking & cost
    token_cost_input_per_million: float
    token_cost_output_per_million: float
    max_stage_cost_usd: float

    @classmethod
    def from_env(cls) -> Config:
        """Build a ``Config`` from the current environment variables."""
        return cls(
            groq_api_key=settings.groq_api_key(),
            groq_model=settings.groq_model(),
            groq_timeout=settings.groq_timeout(),
            groq_max_retries=settings.groq_max_retries(),
            code_temperature=settings.code_temperature(),
            theme_temperature=settings.theme_temperature(),
            interpretation_temperature=settings.interpretation_temperature(),
            embedding_model=settings.embedding_model(),
            model_cache_dir=settings.model_cache_dir(),
            batch_size=settings.batch_size(),
            log_level=settings.log_level(),
            data_path=settings.data_path(),
            tags_path=settings.tags_path(),
            processed_data_path=settings.processed_data_path(),
            bm25_tokenizer_config=settings.bm25_tokenizer_config(),
            fewshot_enabled=settings.fewshot_enabled(),
            fewshot_count=settings.fewshot_count(),
            fewshot_shuffle=settings.fewshot_shuffle(),
            token_cost_input_per_million=settings.token_cost_input_per_million(),
            token_cost_output_per_million=settings.token_cost_output_per_million(),
            max_stage_cost_usd=settings.max_stage_cost_usd(),
        )
