---
title: "68 — logs-and-observability"
description: "Structured JSON logging; stage events; log aggregation script"
updated_at: "2026-05-12"
phase: 11
---

# Feature 68: logs-and-observability


---

## Description

Structured JSON logging throughout. Each log entry: `timestamp`, `level`, `component`, `message`, `stage`, `duration_ms` (if timed). Log aggregation script `scripts/summarize_logs.py` reads `data/output/app.log` and produces summary: total runs, stage durations, error counts, token usage totals.

---

## Acceptance Criteria

- All modules use `get_logger(__name__)`
- Start/end of each stage logged with `stage_start` / `stage_end` events
- Errors logged with `error_type` and `stack_trace` fields
- Log rotation: daily files `app.log.YYYY-MM-DD`
- Summary script produces table: stage | runs | avg_duration_ms | errors
- Logs parseable by `jq` for ad-hoc queries

---

## Dependencies

@docs/plan/03-logging-framework.md

---

## Implementation Notes

- Module: all modules import `from utils.logging import get_logger`
- Stage wrappers: decorator `@log_stage(stage_name)` logs start/end/duration
- Error handler: `except Exception as e: logger.error("Unhandled", exc_info=True, extra={"error_type": type(e).__name__})`
- Rotating file handler: `TimedRotatingFileHandler('data/output/app.log', when='midnight', backupCount=7)`
- Summary script: read log lines, filter by `stage_start/end`, compute duration per stage run, aggregate via pandas/polars
- JSON format ensures `jq '. | select(.level=="ERROR")'` works

---

**References:** None
