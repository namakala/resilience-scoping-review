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


def _optional_float(
    key: str, default: float, lo: float = 0.0, hi: float = 2.0
) -> float:
    """Parse a float env var, clamped to [*lo*, *hi*]."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        val = float(raw)
        if not lo <= val <= hi:
            raise ValueError
        return val
    except ValueError:
        raise ConfigurationError(
            f"{key!r} must be a float in [{lo}, {hi}], got {raw!r}"
        )


# ── Groq / LLM ─────────────────────────────────────────────────────────────


def groq_api_key() -> str:
    """Groq API key (required)."""
    return _required(
        "GROQ_API_KEY",
        "Create a .env file with GROQ_API_KEY=your_key or export it.",
    )


def default_model() -> str:
    """Default LLM model for all inference stages (fallback for per-stage models)."""
    val = os.getenv("DEFAULT_MODEL")
    if not val:
        val = os.getenv("MODEL_NAME")
    return val or "openai/gpt-oss-120b"


def code_model() -> str:
    """Override model for code inference stage. Falls back to default_model()."""
    return os.getenv("CODE_MODEL") or default_model()


def theme_model() -> str:
    """Override model for theme inference stage. Falls back to default_model()."""
    return os.getenv("THEME_MODEL") or default_model()


def interpretation_model() -> str:
    """Override model for interpretation synthesis stage.
    Falls back to default_model()."""
    return os.getenv("INTERPRETATION_MODEL") or default_model()


def groq_timeout() -> int:
    """Groq client timeout in seconds."""
    return _optional_int("GROQ_TIMEOUT", 60)


def groq_max_retries() -> int:
    """Groq client max retries (initial; custom retry wrapper overrides)."""
    return _optional_int("GROQ_MAX_RETRIES", 2)


# ── Inference Temperatures ─────────────────────────────────────────


def code_temperature() -> float:
    """Temperature for code inference LLM calls (default: 0.3)."""
    return _optional_float("CODE_TEMPERATURE", 0.3)


def theme_temperature() -> float:
    """Temperature for theme inference LLM calls (default: 0.4)."""
    return _optional_float("THEME_TEMPERATURE", 0.4)


def interpretation_temperature() -> float:
    """Temperature for interpretation synthesis LLM calls (default: 0.5)."""
    return _optional_float("INTERPRETATION_TEMPERATURE", 0.5)


# ── HuggingFace Hub ─────────────────────────────────────────────────────────


def hf_hub_offline() -> bool:
    """Skip all HTTP requests to HuggingFace Hub (load models from cache only).

    When set to ``True`` (e.g. ``HF_HUB_OFFLINE=1``), the ``huggingface_hub``
    library will not make any network requests.  Used by ``sentence-transformers``
    to avoid the update-version check on every model load.
    """
    raw = os.getenv("HF_HUB_OFFLINE", "false")
    return raw.lower() in ("true", "1", "yes")


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


def export_output_path() -> Path:
    """Directory for exported results (JSON, CSV, Markdown)."""
    return Path(_optional_str("EXPORT_OUTPUT_PATH", "data/output"))


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
