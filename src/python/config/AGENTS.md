---
title: "Configuration Layer"
description: "Centralized env var loading with dotenv, typed accessors, defaults, and validation"
updated_at: "2026-05-14"
---

# Configuration Layer

Loads `.env` via `python-dotenv` on import. Exposes all application settings
as typed module-level functions with sensible defaults and validation.

## Settings

All settings documented in `.env.example`. Key groups:

- **Groq/LLM:** `groq_api_key()` (required), `groq_model()`, `groq_timeout()`,
  `groq_max_retries()`
- **Inference Temperatures:** `code_temperature()`, `theme_temperature()`,
  `interpretation_temperature()`
- **Embedding:** `embedding_model()`, `model_cache_dir()`
- **Processing:** `batch_size()`, `log_level()`
- **Paths:** `data_path()`, `tags_path()`, `processed_data_path()`
- **BM25:** `bm25_tokenizer_config()`
- **Few-Shot:** `fewshot_enabled()`, `fewshot_count()`, `fewshot_shuffle()`

## Design

- `load_dotenv()` called once at module level — no repeated I/O
- Required vars use `_required()` helper — raise `ConfigurationError` if missing
- Integer vars use `_optional_int()` — validates parseability
- Path vars return `Path` objects, `~` expanded
- Functions not cached — each call re-reads `os.environ` for testability
- Tests override env vars via `@mock.patch.dict(os.environ, ...)`

## Dependencies

- `python-dotenv` for `.env` loading

## References

Used by all downstream layers. See `@docs/plan/30-groq-client-initialization.md`.
