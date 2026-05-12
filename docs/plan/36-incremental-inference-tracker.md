---
title: "36 — incremental-inference-tracker"
description: "Track pending exemplars/codes; skip already-inferred on re-run"
updated_at: "2026-05-12"
phase: 5
---

# Feature 36: incremental-inference-tracker


---

## Description

Track which exemplars have pending code generation. Table `inference_status(entity_id, entity_type, stage, status, last_attempt_at, attempts)`. For code stage: exemplars without approved code or with `status='draft'` are pending. On re-run, only pending items batched. Completed (approved/rejected) items skipped.

---

## Acceptance Criteria

- After initial code inference run, all exemplars have status=`generated` (not yet approved)
- Edits to code that change definition reset status to `draft` and increment `attempts`
- Filter function `get_pending_items(stage, tag=None)` returns only items needing inference
- Re-run after HITL edits processes only changed items
- Status table queried manually for debugging

---

## Dependencies

@docs/plan/07-duckdb-schema-init.md
@docs/plan/37-code-inference-service.md (logical dependency)

---

## Implementation Notes

- Module: `src/python/inference/tracker.py`
- Table: `inference_status(entity_id, entity_type, stage, status, last_attempt_at TIMESTAMP, attempts INT)`
- Statuses: `pending`, `generated`, `approved`, `rejected`, `draft` (after edit)
- After inference batch, update status: `INSERT OR REPLACE INTO inference_status VALUES (...)`
- `get_pending_items(stage, tag=None) → list[entity_id]`: `SELECT entity_id FROM inference_status WHERE stage=? AND status IN ('pending','draft') [AND tag=?]`
- Called by batch-grouping (Feature 32) to filter items before grouping

---

**References:** ADR-007 (Incremental Evolution)
