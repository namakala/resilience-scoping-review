---
title: "30 — groq-client-initialization"
description: "Load GROQ_API_KEY; create async client with timeout/retry"
updated_at: "2026-05-12"
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

**References:** ADR-010 (LLM Inference Strategy)
