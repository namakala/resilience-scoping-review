---
title: "51 — interpretation-approval-finalizes"
description: "Approve marks interpretation final; invalidates caches; completes branch"
updated_at: "2026-05-15"
phase: 8
---

# Feature 51: interpretation-approval-finalizes


---

## Description

When interpretation approved:
- Mark node status=`approved`
- Invalidate caches for all tag_spans (subtree caches need update)
- Set `dirty_flags` for those tags to trigger final indexing
- Increment `user_action_count` and log approval
- Interpretation considered complete; no further edits allowed (only via new interpretation)

---

## Acceptance Criteria

- Approved interpretation appears in final export
- Status transition irreversible (cannot revert from approved to draft)
- Downstream caches refreshed on next pipeline run
- Session `approved_interpretation_count` incremented
- Audit log entry includes timestamp, user_id, old_status, new_status

---

## Dependencies

@docs/plan/49-interpretation-hitl-cli.md
@docs/plan/20-incremental-cache-invalidation.md

---

## Implementation Notes

- Module: `src/python/hitl/approvals.py`
- In `approve_interpretation(interp_id)` function:
  - `UPDATE nodes SET status='approved', updated_at=now() WHERE id=?`
  - Get interpretation's `tag_spans` from node `data_json`
  - For each tag in `tag_spans`: `invalidate_cache_for_tag(tag)` (Feature 20); set `dirty_flags[tag]=True`
  - Increment session counter: `UPDATE session_state SET value = json_set(value, '$.approved_interpretation_count', json_extract(value, '$.approved_interpretation_count') + 1) WHERE key='workflow'`
  - Log: `INSERT INTO user_actions ...`
- After approval, interpretation not editable; HITL shows "Approved" and non-editable

---

**References:** ADR-011
