---
title: "16 — graph-transactional-updates"
description: "Atomic batch operations across DuckDB and NetworkX"
updated_at: "2026-05-13"
phase: 2
---

# Feature 16: graph-transactional-updates


---

## Description

Batch operations execute atomically across DuckDB and NetworkX. Use explicit transaction: `with graph_transaction(): ...` context manager. On any exception, roll back both persistence and in-memory changes.

---

## Acceptance Criteria

- Context manager starts DuckDB transaction
- Within block, multiple `create_node`/`create_edge` calls succeed or fail together
- On exception, DuckDB rolls back (no partial rows); NetworkX changes reverted via checkpoint/restore
- Nested transactions not supported (single-level only)
- Unit test: force exception mid-batch → database unchanged
- Deadlock handling: retry once on database lock error

---

## Dependencies

@docs/plan/12-node-insertion-api.md
@docs/plan/13-edge-creation-api.md

---

## Implementation Notes

- Module: `src/python/graph/transactions.py`
- DuckDB: `conn.execute("BEGIN")` ... `conn.execute("ROLLBACK")` on error
- NetworkX: snapshot graph state on enter; restore on exit
- Savepoint not needed; single transaction per batch
- Retry decorator (Feature 04) for deadlock: `@retry` on `DuckDBError` with "lock" in message

---

**References:** ADR-004
