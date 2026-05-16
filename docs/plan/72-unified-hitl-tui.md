---
title: "Unified HITL TUI with Textual"
description: "Interactive terminal UI replacing questionary-based review with tabbed dual-pane browser"
updated_at: "2026-05-16"
---

# Unified HITL TUI

Replaces the old questionary-based interactive CLI with a Textual-based terminal UI.

## Changes

### Bug Fixes (Phase A)

1. **A-1 state.py**: Added `_extra_fields` to `WorkflowState` so `interpretation_ready_tags` (and any future extra keys) survive checkpoint saves. Fixes the root cause of "interpretation review never happens."

2. **A-2 theme_postprocess.py**: Added `auto_merge_single_code_themes()` called after `flag_small_themes()` in theme inference. Single-code themes are automatically merged into the nearest multi-code theme in the same tag.

3. **A-3 shared.py + action handlers**: `_update_node_name()` helper added. All three `handle_edit*` functions now accept `new_name` parameter alongside `new_definition`/`new_narrative`.

4. **A-4 query modules**: Added `get_all_codes()`, `get_all_codes_for_tag()`, `get_all_themes()`, `get_all_themes_for_tag()`, `get_all_interpretations()` — fetch entities without `status='draft'` filter, enabling browsing of all statuses.

### TUI Build (Phase B)

5. **B-1 pyproject.toml**: Added `textual>=1.0.0` dependency.

6. **B-2 app.py**: `AnalystTUI` Textual App with 4 tabs (Logs, Codes, Themes, Interpretations). Pipeline runs in a background thread via `run_worker`. Review stages enable the relevant tab and block until user completes all pending items.

7. **B-3 entity_browser.py**: Dual-pane widget — left `ListView` with status icons, right detail `Static` with expandable sections (first 3 exemplars + "N more"). Keyboard navigation with j/k.

8. **B-4 modals.py**: `EditModal` (name + definition), `MergeModal` (candidate list), `SplitModal` (theme selection with space toggle).

9. **B-5 actions/handlers.py**: Thin wrappers dispatching TUI key events to existing backend action handlers.

10. **B-5 run.py**: `run_sequence()` detects TTY and launches TUI when running interactively without `--type` filter. Falls back to old sequential pipeline in CI/piped output.

11. **B-6 Deprecation**: `code_review.py`, `theme_review.py`, `interpretation_review.py` marked deprecated with `DeprecationWarning`.

## Files Modified

- `pyproject.toml` — added textual dependency
- `src/python/orchestration/state.py` — added `_extra_fields`
- `src/python/orchestration/run.py` — TUI auto-launch
- `src/python/hitl/shared.py` — added `_update_node_name`
- `src/python/hitl/code_review_actions.py` — `handle_edit` accepts `new_name`
- `src/python/hitl/theme_review_actions.py` — `handle_edit_theme` accepts `new_name`
- `src/python/hitl/interpretation_review_actions.py` — `handle_edit_interpretation` accepts `new_name`
- `src/python/hitl/queries_codes.py` — added `get_all_codes`, `get_all_codes_for_tag`
- `src/python/hitl/queries_themes.py` — added `get_all_themes`, `get_all_themes_for_tag`
- `src/python/hitl/queries_interpretations.py` — added `get_all_interpretations`
- `src/python/hitl/code_review.py` — deprecation warning added
- `src/python/hitl/theme_review.py` — deprecation warning added
- `src/python/hitl/interpretation_review.py` — deprecation warning added
- `src/python/inference/theme_postprocess.py` — added `auto_merge_single_code_themes`
- `src/python/inference/theme_inference.py` — calls auto-merge after flag_small_themes

## Files Created

- `src/python/hitl/tui/__init__.py` — re-exports `AnalystTUI`
- `src/python/hitl/tui/app.py` — main `AnalystTUI` app
- `src/python/hitl/tui/widgets/__init__.py`
- `src/python/hitl/tui/widgets/entity_browser.py` — dual-pane browser
- `src/python/hitl/tui/widgets/modals.py` — edit/merge/split modals
- `src/python/hitl/tui/actions/__init__.py`
- `src/python/hitl/tui/actions/handlers.py` — action dispatch wrappers
