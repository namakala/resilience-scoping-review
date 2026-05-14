---
title: "30 — groq-client-initialization"
description: "Load GROQ_API_KEY; create async client with timeout/retry"
updated_at: "2026-05-13"
phase: 5
---

# Feature 30: groq-client-initialization


---

## Description

Load `GROQ_API_KEY` from environment (fail-fast if missing). Create Groq async client with timeout=60s, max_retries=2 (initial; we implement our own retry wrapper). Configure model: `openai/gpt-oss-120b` (or specified via `--model`). Initialize client singleton accessible to all inference modules.

---

## Acceptance Criteria

- Client creation succeeds with valid key
- Missing key raises `ConfigurationError` with instruction to set `.env`
- Client tested with dry-run `chat.completions.create(messages=[{"role":"user","content":"test"}], max_tokens=5)` returns valid response structure
- Async client used throughout; sync wrappers provided where needed
- Client connection pooled (reused across batches)

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

- Module: `src/python/inference/groq_client.py`
- `from groq import AsyncGroq`; `client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"), timeout=60, max_retries=2)`
- Model: `model="openai/gpt-oss-120b"` or env `GROQ_MODEL`
- Singleton: module-level `_client` variable; `get_client()` accessor
- Dry-run in Feature test: `await client.chat.completions.create(...)` with `max_tokens=1`

---

## Implementation Completion

**Completed:** 2026-05-13

All acceptance criteria satisfied:

- Created `src/python/config/` package with typed settings for all env vars
  from `.env.example` (Groq, embedding, processing, paths, BM25)
- Created `src/python/inference/groq_client.py` with async/sync singleton
  clients, `get_client()`, `get_sync_client()`, `get_model()`, `set_client()`,
  `reset_client()`
- Added `ConfigurationError` to `utils/exceptions.py` for missing/invalid config
- Added `groq>=1.2.0` and `python-dotenv>=1.0.0` to `pyproject.toml`
- 25 config tests cover all env var accessors (required, optional, defaults,
  type validation, fallback chains)
- 10 groq client tests cover missing key, client creation, singleton,
  DI injection, reset, independent sync/async, model overrides
- Full test suite: 520 passed, 0 failures, no regressions

**Deviation from original plan:**

- Added dedicated `config/` package for centralized typed settings rather than
  inline `os.getenv` calls in `groq_client.py`. Settings functions read from
  `os.environ` at call time (not cached) for testability.
- Added `python-dotenv` dependency for automatic `.env` loading at import time.
- Sync client (`Groq`) alongside async (`AsyncGroq`), both as singletons.

**Git:** Not committed (user discretion).

**References:** ADR-010 (LLM Inference Strategy)
