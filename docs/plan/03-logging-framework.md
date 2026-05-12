---
title: "03 — logging-framework"
description: "Centralized JSON-structured logging with rotation"
updated_at: "2026-05-12"
phase: 0
---

# Feature 03: logging-framework


---

## Description

Implement centralized structured logging using Python's `logging` module with JSON formatter. Logs written to `data/output/app.log` with daily rotation. Log levels configurable via environment variable `LOG_LEVEL`.

---

## Acceptance Criteria

- `get_logger(name: str) -> logging.Logger` returns configured logger
- All log entries are JSON with fields: `timestamp`, `level`, `logger`, `message`, `module`, `function`
- File handler rotates at midnight; retains 7 days
- Console handler prints human-readable format for development
- Sensitive data (API keys, PII) filtered via custom filter

---

## Dependencies

@docs/plan/00-environment-provisioning.md

---

## Implementation Notes

- Module: `src/python/utils/logging.py`
- JSON format: `{"timestamp":"...", "level":"INFO", "logger":"...", ...}`
- Sensitive filter: redact patterns like `GROQ_API_KEY`, `password`, `token`
- `LOG_LEVEL` defaults to `INFO`

---

**References:** None
