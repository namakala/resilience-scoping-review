---
title: "63 — error-recovery-handler"
description: "Groq retry; DuckDB corruption rebuild; Ctrl-C graceful; exit codes"
updated_at: "2026-05-12"
phase: 10
---

# Feature 63: error-recovery-handler


---

## Description

Robust error handling at orchestration level. Groq timeout → retry (delegated to inference layer). DuckDB corruption → attempt checkpoint rebuild from artifacts (re-run stage 1–3). Unhandled exception → save state, log error, exit with non-zero code. Ctrl-C → graceful shutdown (save state, close connections).

---

## Acceptance Criteria

- On Groq network failure, retries exhausted → logs batch_id, error, continues to next batch if possible; stage summary includes failure count
- On DuckDB `DatabaseError`, attempts `PRAGMA integrity_check`; if fail, rebuilds database from Parquet artifacts and resumes from last complete stage
- On Ctrl-C (SIGINT), writes `last_checkpoint`, closes file handles, exits with code 0 (clean exit)
- Unrecoverable errors logged with full stack trace and `error_type` field
- Exit codes: 0=success, 1=user interrupt, 2=config error, 3=storage corruption, 4=API failure

---

## Dependencies

@docs/plan/58-cli-entrypoint.md
@docs/plan/35-retry-and-rate-limit-handling.md

---

## Implementation Notes

- Module: `src/python/orchestration/errors.py`
- Top-level `main()` wrapped in `try/except`:
  ```python
  try:
      run_pipeline()
  except KeyboardInterrupt:
      save_state(state); logger.info("Interrupted by user"); sys.exit(1)
  except DuckDBError as e:
      if integrity_check_fails(): rebuild_database(); resume_from_last_stage()
      else: raise
  except Exception as e:
      save_state(state); logger.error("Unhandled", exc_info=True); sys.exit(4)
  ```
- `rebuild_database()`: drop all tables; re-run Features 05–07 to recreate from Parquet
- Exit codes defined in constants

---

**References:** None
