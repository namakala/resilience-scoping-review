---
title: "43 — theme-node-creation"
description: "Convert ThemeInference to graph nodes and composed-of edges"
updated_at: "2026-05-14"
phase: 7
---

# Feature 43: theme-node-creation

---

## Description

Convert each `ThemeInference` item into a graph node and edges. Node: `type='theme'`, `name=theme_name`, `definition=narrative`, `tag=parent_tag` (inherited from constituent codes), `status='draft'`. Edges: `composed-of` from theme to each code_id. If theme re-generated, `derived-from` chain maintained.

---

## Acceptance Criteria

- One theme node per `ThemeInference` item
- `composed-of` edges correctly link theme → codes
- Query `get_nodes_by_type_and_tag('theme', tag)` returns all themes for that tag
- `derived-from` chain tracks theme evolution across re-inference
- All nodes and edges persisted transactionally
- Duplicate theme names within tag flagged (merge later in HITL)

---

## Dependencies

@docs/plan/42-theme-inference-service.md
@docs/plan/14-node-query-operations.md

---

## Implementation Notes

- Module: `src/python/inference/theme_creation.py` → split into 3 files during refactor

### Files Created

**`src/python/inference/create_theme_nodes.py`** (~95 lines) — Orchestrator
- `_build_data_json()` helper
- `create_theme_nodes(con, themes, tag, db_path)` — public API
- Input validation, re-inference detection, `graph_transaction` block, post-tx status update
- Imports graph helpers from `theme_node_reinfer` and name utilities from `theme_name_utils`

**`src/python/inference/theme_node_reinfer.py`** (~55 lines) — Graph mutation helpers
- `load_existing_draft_themes(tag, db_path)` → `{name: node_id}`
- `rename_node_raw(node_id, new_name, db_path)` — DuckDB + NetworkX rename inside transaction

**`src/python/inference/theme_name_utils.py`** (~55 lines) — Name collision utilities
- `make_unique_theme_name(name, used_names)` → dedup with `_1`, `_2` suffix
- `check_duplicate_theme_names(themes)` → warn on same-batch duplicates

### Per-theme node creation flow

  - `theme_id = create_node(type='theme', name=theme_name, definition=narrative, tag=parent_tag, status='draft', data_json={})`
  - For each `code_id` in `code_ids`: `create_edge(source_id=theme_id, target_id=code_id, edge_type='composed-of')`
  - Check for existing draft theme with same name; link via `derived-from` if regenerated
- Transaction via `graph_transaction()`
- Update `inference_status` for codes to `themed` (handled by theme inference service)

---

**References:** ADR-004
