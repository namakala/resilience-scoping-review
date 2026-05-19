---
title: "Textual TUI Module"
description: "Textual-based interactive review interface with tabbed entity browser and action dispatch"
updated_at: "2026-05-18"
---

# Textual TUI Module

Textual-based terminal UI for HITL review. Tabbed interface with Logs, Codes, Themes, and Interpretations tabs.

## Architecture

**`app.py`** — `AnalystTUI` main application. Pipeline execution thread, tab management, action keybindings (`e/a/r/m/s/d/f`), modal push.

**`widgets/entity_browser.py`** — `EntityBrowser` dual-pane widget. Left: scrollable entity list with status icons, search input, and active filter indicator. Right: detail pane with definition, semantic neighbors, evidence chain. Supports status filtering via keybinding `f`.

**`widgets/modals.py`** — `EditModal`, `MergeModal`, `SplitModal` for user input.

**`widgets/status_filter_modal.py`** — `StatusFilterModal` checklist screen for selecting which entity statuses to display. Uses ``SelectionList[str]`` with all six status values. Press `f` in any review tab to open.

**`actions/handlers.py`** — Dispatch layer bridging keybindings to backend action handlers in `hitl.code_review_actions`, `hitl.theme_review_actions`, `hitl.interpretation_review_actions`. Split dispatches to `hitl.code_review_split`, `hitl.theme_review_split`, or `hitl.interpretation_review_split` by entity type.

## Actions

Seven actions available via single-key bindings:
- `e` — Edit (opens modal)
- `a` — Approve
- `r` — Reject
- `m` — Merge (opens modal)
- `s` — Split (iterative multi-modal: each round shows remaining items; triggers LLM re-inference after all groups collected)
- `d` — Defer (log only, entity stays in review queue)
- `f` — Filter (opens StatusFilterModal checklist to pick which statuses to display)

Default filter shows `draft`, `pending`, and `approved` entities. Use `f` to toggle any combination of `draft`, `pending`, `approved`, `rejected`, `merged`, or `superseded`.

## Pipeline Integration

Pipeline runs in a background thread. Review stages enable tabs and poll until all `draft` entities are processed. Defer keeps entity in `draft` — pipeline advances only when all items are approved, rejected, or merged.

## References

Uses shared backend handlers from `hitl.code_review_actions`, `hitl.theme_review_actions`, `hitl.interpretation_review_actions`, `hitl.code_review_split`, `hitl.theme_review_split`, `hitl.interpretation_review_split`. See `@../AGENTS.md` for module overview.
