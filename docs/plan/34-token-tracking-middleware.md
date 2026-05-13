---
title: "34 — token-tracking-middleware"
description: "Log input/output tokens; accumulate session totals; estimate cost"
updated_at: "2026-05-14"
phase: 5
---

# Feature 34: token-tracking-middleware


---

## Description

Wrap Groq API calls to log token usage: `input_tokens`, `output_tokens` from response `usage` field. Accumulate per-session totals in `session_state` or in-memory counter. Estimate cost: input $0.15/1M tokens, output $0.60/1M tokens (configurable rates). Log per-batch and per-stage summary to `data/output/token_usage.log`.

---

## Acceptance Criteria

- After each LLM call, writes structured log: `{"stage":"code_inference","batch_id":"...","input_tokens":1234,"output_tokens":567,"cost_usd":0.12}`
- Session totals displayed at end of each stage: "Code inference complete. Tokens: 50K in, 20K out. Cost: $0.015"
- Cost calculation verified with manual arithmetic test
- Token counts also stored in `session_state` for later reporting
- Warning logged if stage cost exceeds configurable threshold (default $1.00)

---

## Dependencies

@docs/plan/30-groq-client-initialization.md
@docs/plan/10-session-state-manager.md

---

## Implementation Notes

- Module: `src/python/inference/tracking.py`
- Decorator or wrapper: `@track_tokens(stage_name)` around inference function
- Extract from response: `resp.usage.prompt_tokens`, `resp.usage.completion_tokens`
- Session accumulator: in-memory dict `{stage: {in, out}}`; flush to `session_state` after stage
- Cost rates configurable via environment: `TOKEN_COST_INPUT_PER_MILLION`, `TOKEN_COST_OUTPUT_PER_MILLION`
- Warning threshold: `MAX_STAGE_COST_USD=1.00`

---

---

## Implementation Completion

**Completed:** 2026-05-14

All acceptance criteria satisfied:

- **AC #1:** Structured JSONL written to `data/output/token_usage.log` — each line contains `stage`, `batch_id`, `input_tokens`, `output_tokens`, `cost_usd`, `timestamp`
- **AC #2:** `format_stage_summary()` produces human-readable summary: `"Code inference complete. Tokens: 50K in, 20K out. Cost: $0.015"`
- **AC #3:** Cost calculation verified with manual arithmetic test across multiple rate configurations
- **AC #4:** `flush_to_dict()` and `flush_to_records()` produce session_state-compatible dicts; extra keys preserved by state manager
- **AC #5:** `logger.warning` triggered once per stage when cumulative stage cost exceeds `MAX_STAGE_COST_USD` (default $1.00)

### Implementation Details

- **Module:** `src/python/inference/tracking.py`
- **Config added:** `token_cost_input_per_million()`, `token_cost_output_per_million()`, `max_stage_cost_usd()` in `src/python/config/settings.py` (exported via `config/__init__.py`)
- **API surface:**
  - `TokenTracker` class: `record()`, `stage_summary()`, `session_summary()`, `recent_usage()`, `flush_to_dict()`, `flush_to_records()`, `reset()`
  - `get_tracker()` / `reset_tracker()` — singleton accessors
  - `@track_tokens(stage_name)` — decorator wrapping functions that return ChatCompletion-like objects
  - `format_stage_summary()` — formatted stage completion message
- **Enhanced for Feature 35:** `recent_usage(window_seconds=60)` exposes a sliding window of tokens used, enabling rate-limit pre-flight checks in the retry/rate-limit module
- **Env vars:** `TOKEN_COST_INPUT_PER_MILLION`, `TOKEN_COST_OUTPUT_PER_MILLION`, `MAX_STAGE_COST_USD` — all documented in `.env.example`
- **Tests:** 41 tests in `tests/unit/inference/tracking_test.py` covering recording, accumulation, cost math, persistence, warnings, singleton, decorator, edge cases (zero tokens, log directory creation)
- No regressions: 643 total tests pass

**References:** ADR-010
