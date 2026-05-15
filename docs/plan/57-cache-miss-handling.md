---
title: "57 — cache-miss-handling"
description: "Nodes check persistence layer for cached values; recompute if missing/stale"
updated_at: "2026-05-15"
phase: 9
---

# Feature 57: cache-miss-handling


---

## Description

Nodes check persistence layer for cached values before computing. If cache valid (content_hash matches), then load; otherwise compute and store. Cache invalidation triggered by dirty flags.

---

## Acceptance Criteria

- On resume after crash, `dag.execute()` picks up from last checkpoint without recomputing completed nodes
- Cache miss detected when `content_hash` changed or entry missing
- Node logs: `"cache hit for node X"` or `"cache miss: computing"`
- Corrupted cache entries auto-rebuilt from source artifacts
- Node execution idempotent: running twice yields same result

---

## Dependencies

@docs/plan/56-selective-execution.md
@docs/plan/08-embedding-cache-schema.md

---

## Implementation Notes

- Module: `src/python/pipeline/caching.py`
- Each node with cache: before compute, call `load_cached(node_id, inputs_hash)`
- `inputs_hash = sha256(json.dumps(sorted(inputs.items()))).hexdigest()`
- Cache table: `node_cache(node_id, inputs_hash, output_blob, timestamp)`
- If `SELECT 1 FROM node_cache WHERE node_id=? AND inputs_hash=?` → return deserialized; else compute
- After compute, `INSERT INTO node_cache ...`
- Corruption: on deserialize error, delete row and recompute
- Idempotency ensured by deterministic node functions

---

**References:** ADR-008
