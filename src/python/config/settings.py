"""Application settings loaded from environment variables + .env file.

Loads .env via python-dotenv on import. Each setting is a typed function
reading directly from os.environ for testability.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from utils.exceptions import ConfigurationError

load_dotenv()

# ── Helpers ────────────────────────────────────────────────────────────────


def _required(key: str, hint: str = "") -> str:
    val = os.getenv(key)
    if not val:
        msg = f"Required environment variable {key!r} is not set."
        if hint:
            msg += f" {hint}"
        raise ConfigurationError(msg)
    return val


def _optional_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _optional_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigurationError(f"{key!r} must be an integer, got {raw!r}")


# ── Groq / LLM ─────────────────────────────────────────────────────────────


def groq_api_key() -> str:
    """Groq API key (required)."""
    return _required(
        "GROQ_API_KEY",
        "Create a .env file with GROQ_API_KEY=your_key or export it.",
    )


def groq_model() -> str:
    """LLM model name. Checks GROQ_MODEL first, falls back to MODEL_NAME."""
    val = os.getenv("GROQ_MODEL")
    if val:
        return val
    return os.getenv("MODEL_NAME", "openai/gpt-oss-120b")


def groq_timeout() -> int:
    """Groq client timeout in seconds."""
    return _optional_int("GROQ_TIMEOUT", 60)


def groq_max_retries() -> int:
    """Groq client max retries (initial; custom retry wrapper overrides)."""
    return _optional_int("GROQ_MAX_RETRIES", 2)


# ── Embedding Model ────────────────────────────────────────────────────────


def embedding_model() -> str:
    """Sentence-transformer model for embeddings."""
    return _optional_str("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def model_cache_dir() -> Path:
    """HuggingFace model cache directory."""
    return Path(
        _optional_str("MODEL_CACHE_DIR", "~/.cache/huggingface/hub")
    ).expanduser()


# ── Processing ─────────────────────────────────────────────────────────────


def batch_size() -> int:
    """Exemplars per inference batch."""
    return _optional_int("BATCH_SIZE", 15)


def log_level() -> str:
    """Logging level (DEBUG, INFO, WARNING, ERROR)."""
    return _optional_str("LOG_LEVEL", "INFO")


# ── Paths ──────────────────────────────────────────────────────────────────


def data_path() -> Path:
    """Path to raw exemplars CSV."""
    return Path(_optional_str("DATA_PATH", "data/raw/data.csv"))


def tags_path() -> Path:
    """Path to raw tags CSV."""
    return Path(_optional_str("TAGS_PATH", "data/raw/tags.csv"))


def processed_data_path() -> Path:
    """Base directory for processed Parquet artifacts."""
    return Path(_optional_str("PROCESSED_DATA_PATH", "data/processed"))


# ── BM25 ───────────────────────────────────────────────────────────────────


def bm25_tokenizer_config() -> str:
    """Comma-separated tokenizer pipeline toggles."""
    return _optional_str("BM25_TOKENIZER_CONFIG", "lowercase,split_by_space")


# ── Few-Shot ───────────────────────────────────────────────────────────────


def fewshot_enabled() -> bool:
    """Global toggle for few-shot demonstrations."""
    raw = os.getenv("FEWSHOT_ENABLED", "true")
    return raw.lower() not in ("false", "0", "no")


def fewshot_count() -> int:
    """Number of few-shot examples per inference call."""
    return _optional_int("FEWSHOT_COUNT", 2)


def fewshot_shuffle() -> bool:
    """Randomize few-shot example selection order."""
    raw = os.getenv("FEWSHOT_SHUFFLE", "true")
    return raw.lower() in ("true", "1", "yes")


# ── Token Tracking & Cost ────────────────────────────────────────────


def token_cost_input_per_million() -> float:
    """Cost per 1M input tokens in USD (default: Groq pricing)."""
    raw = os.getenv("TOKEN_COST_INPUT_PER_MILLION")
    if raw is None:
        return 0.15
    try:
        val = float(raw)
        if val < 0:
            raise ValueError
        return val
    except ValueError:
        raise ConfigurationError(
            f"TOKEN_COST_INPUT_PER_MILLION must be a non-negative number, got {raw!r}"
        )


def token_cost_output_per_million() -> float:
    """Cost per 1M output tokens in USD (default: Groq pricing)."""
    raw = os.getenv("TOKEN_COST_OUTPUT_PER_MILLION")
    if raw is None:
        return 0.60
    try:
        val = float(raw)
        if val < 0:
            raise ValueError
        return val
    except ValueError:
        raise ConfigurationError(
            f"TOKEN_COST_OUTPUT_PER_MILLION must be a non-negative number, got {raw!r}"
        )


def max_stage_cost_usd() -> float:
    """Warning threshold for per-stage cost in USD (default: $1.00)."""
    raw = os.getenv("MAX_STAGE_COST_USD")
    if raw is None:
        return 1.00
    try:
        val = float(raw)
        if val < 0:
            raise ValueError
        return val
    except ValueError:
        raise ConfigurationError(
            f"MAX_STAGE_COST_USD must be a non-negative number, got {raw!r}"
        )
