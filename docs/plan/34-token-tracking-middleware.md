---
title: "34 — token-tracking-middleware"
description: "Log input/output tokens; accumulate session totals; estimate cost"
updated_at: "2026-05-12"
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

**References:** ADR-010
