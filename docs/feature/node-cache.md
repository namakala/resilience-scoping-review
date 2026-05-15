---
title: "Node-Level Result Caching"
description: "Deterministic per-node result cache backed by DuckDB, with Hamilton lifecycle adapter for transparent cache hit/miss handling"
updated_at: "2026-05-15"
---

# Node-Level Result Caching

Caches individual Hamilton node outputs in a DuckDB `node_cache` table keyed by `(node_id, inputs_hash)`. Each node checks the cache before computing; a hit returns the stored pickle blob directly, a miss computes, stores, and returns.

## Purpose & Design Rationale

Hamilton v1.90 ships `SmartCacheAdapter` with `MetadataStore`/`ResultStore` abstractions, but we chose a pure DuckDB approach for three reasons:

1. **Deterministic key semantics** — `inputs_hash = sha256(json.dumps(sorted(inputs.items())))` produces a stable value-based key. Hamilton's `cache_key` incorporates a `code_version` (source-code hash) which triggers spurious invalidation on whitespace/docstring changes. Node cache invalidates only on *actual value changes*, matching ADR-005's content-hash invalidation pattern used by `embedding_cache`.
2. **Single source of truth** — All pipeline state (session state, embedding cache, ontology graph) lives in the same DuckDB file. Adding node results keeps them SQL-queryable alongside the rest: `SELECT count(*) FROM node_cache` works without cross-store joins.
3. **Crash resume explicitness** — The adapter intercepts `do_node_execute` and returns cached results transparently. Hamilton needs no special setup; any `Builder().with_modules(...)` pipeline gains caching by appending `NodeCacheAdapter` to the adapter chain.

### Hamilton SmartCacheAdapter Trade-offs Mitigated

| Concern | Mitigation |
|---|---|
| `inputs_hash` blind to code changes | Intentionally limited scope: code changes invalidate via dirty flags (Feature 55), not node cache. Cache is *value-based*, not *code-based*. |
| Manual BLOB management | `pickle.dumps(result)` mirrors the existing BM25 persistence pattern in `semantic/persistence.py`. Single serialization format, fully tested. |
| No automatic task-parallel cache | Top-level nodes (embed, index, retrieve) are cache targets; sub-batch inference runs inside a single node call. Batches are not individually cached. |
| `_normalize_input_value` must handle Polars/NetworkX/NumPy | Explicit serializers for each type (schema for LazyFrame, `node_link_data` for DiGraph, `tolist` for ndarray). Unhandleable types fall back to `repr()` with a debug warning. |

## Core Components

**`persistence/node_cache.py`** — DuckDB CRUD: `load_cached(con, node_id, inputs_hash) -> Any|None`, `store_cached(con, node_id, inputs_hash, result)`, `invalidate_node(con, node_id)`, `clear_all_node_cache(con)`. Corruption auto-rebuild: `pickle.UnpicklingError` → `DELETE` → return `None` → caller recomputes.

**`pipeline/caching.py`** — `compute_inputs_hash(inputs_dict) -> str|None`: normalizes kwargs to JSON-safe dicts via `_normalize_value()`, sorts keys, serializes with `json.dumps`, digests with `sha256`.

**`pipeline/cache_adapter.py`** — Hamilton lifecycle adapter: implements `do_node_execute` to intercept per-node execution. Maintains `CacheMetrics` (hit_count, miss_count, cached_nodes set) read by the executor post-run.

**`pipeline/executor.py`** — Refactored `_build_execution_records` to produce `status="cached"` records. Reads `CacheMetrics.cached_nodes` to distinguish cache hits from HITL overrides. Populates `cache_hit_count`/`cache_miss_count`.

**`persistence/duckdb_schema.py`** — New `node_cache` table: `PRIMARY KEY (node_id, inputs_hash)` + index on `inputs_hash`.

## Cacheable Nodes

Only compute-intensive nodes are cached (whitelist in `cache_adapter._CACHEABLE_NODES`): embedding generation (Stage 2), index building (Stage 3), hybrid retrieval (Stages 4/6/8), and LLM inference (Stages 4/6/8). Trivial passthrough nodes (review, export, prepare) execute normally.

Inference nodes ARE cacheable because `dirty_flags` is an external input: if dirty flags change, `inputs_hash` changes, producing a cache miss. On crash resume with identical dirty flags, the LLM call is saved.

## Integration

- **Initialization** — Caller creates `CacheMetrics` + `NodeCacheAdapter(con, metrics)` and appends to `builder.adapters` before `.build()`.
- **Execution** — `execute_dag(driver, cache_metrics=metrics)` reads metrics after `driver.execute()`.
- **Invalidation** — `invalidate_node(con, node_id)` clears all entries for a given node when dirty flags propagate.
- **Observability** — `get_execution_summary()` returns `cache_hit_rate`; SQL queries on `node_cache` return hit/miss breakdowns.

## Constraints

- Node results must be pickleable (standard Python types, Polars DataFrames, NetworkX graphs, plain dicts/lists all OK).
- Cache is input-value-based, not code-version-based. Source patches require manual invalidation or rely on dirty-flag propagation.
- The `_normalize_value` serializer silently downgrades unhandleable types to `repr()`; this may produce false cache collisions (two different objects with same `repr`). Such objects should be excluded from caching by adding their node to the `_SKIP_NODES` set.

## References

Implements Feature 57 (cache-miss-handling). See `@docs/plan/57-cache-miss-handling.md` for acceptance criteria. Compatible with ADR-008 (Pipeline Orchestration) and ADR-007 (Incremental Ontology Evolution). Complements `@docs/feature/semantic-retrieval.md` (retrieval nodes benefit) and `@docs/feature/inference-layer.md` (inference nodes save LLM calls on cache hit).
