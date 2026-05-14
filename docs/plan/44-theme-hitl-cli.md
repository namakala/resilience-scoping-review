---
title: "44 — theme-hitl-cli"
description: "Rich CLI for theme review: approve/edit/merge/reject/defer"
updated_at: "2026-05-14"
phase: 7
status: completed
---

# Feature 44: theme-hitl-cli

Interactive CLI for theme review. For each draft theme:
- Display panel: **Theme name**, **Narrative**
- List constituent codes (name + exemplar count) in table
- Show similar existing themes (up to 3) from `neighbor-discovery-service`
- Prompt: Approve, Edit, Merge, Reject, Defer

Actions:
- **Approve**: status→`approved`; validates ADR-013 constraints (≥2 codes, same tag)
- **Edit**: modify narrative + add/remove codes via checkboxes; status→`draft`
- **Merge**: select another theme; combines code sets; source marked `merged`
- **Reject**: status→`rejected`
- **Defer**: keep `draft`

## Dependencies

@docs/plan/43-theme-node-creation.md
@docs/plan/39-code-hitl-cli.md

## Files Created

| File | Purpose |
|---|---|
| `src/python/hitl/theme_review.py` | Orchestration — `review_themes(con, tag, db_path)` entry point |
| `src/python/hitl/theme_review_actions.py` | Handlers: approve (with constraint check), edit narrative+codes, reject, defer |
| `src/python/hitl/theme_review_prompts.py` | `questionary` prompts: action select, narrative text, code checkbox, merge flow |
| `src/python/hitl/theme_review_display.py` | `rich.Panel` for theme + `rich.Table` for codes and neighbors |
| `src/python/hitl/theme_review_queries.py` | 5 queries: pending themes, constituent codes, neighbors (k=3), available codes, other draft themes |
| `src/python/hitl/theme_review_merge.py` | Transactional merge: redirect `composed-of` edges, combine code sets, invalidate interpretations |

**Updated:** `src/python/hitl/edits.py` (added `invalidate_theme_embedding`), `src/python/hitl/__init__.py` (exports)

## Acceptance Criteria Met

- Code table with ID, name, exemplar count ✓
- Edit allows code list modification; approve validates same-tag constraint ✓
- Merge preview shows combined code list ✓
- Neighbor list up to 3 themes with similarity scores ✓
- All actions logged via `user_action_log` ✓

**Tests:** 10 unit tests in `tests/unit/hitl/theme_review_test.py` (42 total in hitl, no regressions)

**References:** ADR-011
