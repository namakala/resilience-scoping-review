---
title: "04 — error-handling-utilities"
description: "Retry, circuit breaker, graceful shutdown decorators"
updated_at: "2026-05-12"
phase: 0
---

# Feature 04: error-handling-utilities


---

## Description

Provide decorators and context managers for robust error handling: `@retry` (exponential backoff, max attempts configurable), `@circuit_breaker` (fail-fast after threshold), and `graceful_shutdown()` signal handler for Ctrl-C.

---

## Acceptance Criteria

- `@retry(max_attempts=3, backoff=2)` retries function on specified exceptions; sleeps increase exponentially
- `@circuit_breaker(failure_threshold=5, reset_timeout=60)` opens circuit after N failures; blocks calls for reset period
- `with graceful_shutdown():` catches SIGINT/SIGTERM, runs cleanup callbacks, exits cleanly
- Unit tests using `unittest.mock` simulate failures and verify retry/circuit behavior

---

## Dependencies

@docs/plan/00-environment-provisioning.md

---

## Implementation Notes

- Module: `src/python/utils/error_handling.py`
- Retry exceptions: `TimeoutError`, `ConnectionError`, `GroqAPIError` (configurable)
- Circuit breaker state: closed → open → half-open → closed
- Cleanup callbacks: close file handles, save state, close DB connections

---

**References:** None
