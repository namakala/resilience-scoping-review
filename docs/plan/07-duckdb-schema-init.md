---
title: "07 — duckdb-schema-init"
description: "Initialize DuckDB with nodes, edges, traversal_cache, session_state, user_actions"
updated_at: "2026-05-12"
phase: 1
---

# Feature 07: duckdb-schema-init


---

## Description

Initialize DuckDB database at `data/output/session.duckdb`. Create tables: `nodes` (id, type, name, definition, tag, status, data_json, created_at, updated_at), `edges` (source_id, target_id, edge_type, metadata_json), `traversal_cache` (tag, ancestors, descendants, subtree_exemplars, subtree_codes, subtree_themes), `session_state` (key, value), `user_actions` (action_id, timestamp, action_type, entity_id, old_value, new_value, user_id).

---

## Acceptance Criteria

- Database file created on first run
- All tables exist with correct column types and constraints (primary keys, foreign keys where appropriate)
- `nodes.id` and `edges` composite primary key auto-increment
- `session_state` supports JSON values for flexible state storage
- `user_actions` has index on `timestamp` for audit queries
- Schema migration function exists (for future ALTER TABLE needs)

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

- Module: `src/python/persistence/duckdb_init.py`
- Use `CREATE TABLE IF NOT EXISTS`
- `nodes.id` INTEGER PRIMARY KEY AUTOINCREMENT
- `edges` composite PK: `(source_id, target_id, edge_type)`
- `data_json` and `metadata_json` stored as JSON strings (TEXT)
- Migration: store schema version in `session_state` with key `schema_version`

---

**References:** ADR-004 (Graph-Centric), ADR-009
