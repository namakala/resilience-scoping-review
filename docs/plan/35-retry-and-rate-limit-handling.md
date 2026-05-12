---
title: "35 — retry-and-rate-limit-handling"
description: "Exponential backoff, 60s rate-limit wait, batch splitting on token limit"
updated_at: "2026-05-12"
phase: 5
---

# Feature 35: retry-and-rate-limit-handling


---

## Description

Implement retry decorator for Groq calls. On network error (timeout, connection error): exponential backoff delays 2s, 4s, 8s (max 3 attempts). On rate-limit (HTTP 429): sleep 60s then retry once. On token limit exceeded (context-length error): split batch in half and retry each half separately. All retries logged.

---

## Acceptance Criteria

- Simulated failure via mock: function retries correct number of times before final raise
- Rate-limit sleep actually pauses execution (tested with time-monkeypatch)
- Batch splitting: original batch of 20 exemplars split into 10+10; each retried independently
- After 3 network failures, final exception propagates to caller
- Retry count logged per batch for audit

---

## Dependencies

@docs/plan/30-groq-client-initialization.md
@docs/plan/04-error-handling-utilities.md

---

## Implementation Notes

- Module: `src/python/inference/retry.py`
- Use `@retry` from Feature 04 extended for Groq-specific exceptions
- Detect 429: `except groq.APIError as e: if e.status_code == 429: time.sleep(60); retry`
- Token limit: catch `groq.BadRequestError` with "context length" in message; split batch
- Batch splitter: `split_batch_in_half(batch) → [batch1, batch2]`; each retried independently
- Logging: `logger.warning("Retry %d/%d for batch %s after error: %s", attempt, max, batch_id, error)`

---

**References:** ADR-010
