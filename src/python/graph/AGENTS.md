---
title: "Graph Module"
description: "Low-level graph database operations, node/edge CRUD, and DuckDB persistence layer"
updated_at: "2026-05-13"
---

# Graph Module

Provides direct graph database access. Manages nodes, edges, and traversal caches using DuckDB and NetworkX.

## Purpose

Handle persistence of codes, themes, and interpretations. Implement hybrid graph storage: NetworkX for in-memory operations, DuckDB for durable storage.

## Core Responsibilities

- Store semantic entities as nodes (codes, themes, interpretations)
- Store relationships as labeled edges
- Maintain materialized traversal caches (ancestors, descendants, subtree queries)
- Support node lookup, updates, and deletion
- Integrate with DuckDB for transactional durability

## Graph Representation

Dual-model approach:

**In-memory:** NetworkX directed graph for fast traversal and path queries.

**Storage:** DuckDB tables for durability. Nodes stored with type, name, tag, definition, status. Edges stored with source, target, edge type, metadata.

Nodes represent codes, themes, interpretations, and tags (from ontology). Tag nodes are immutable. Mutable nodes evolve with researcher validation.

## Traversal Caching

Repeated subtree traversals are expensive. This module materializes common queries:

- Ancestors of a tag (all parent tags up to root)
- Descendants of a tag (all child tags down to leaves)
- Subtree codes and themes (aggregate semantic evidence)

Caches are stored in DuckDB and invalidated incrementally when ontology changes (new merge, tag addition). Invalidation targets only affected branches to preserve performance.

## Data Operations

Node operations: insert new nodes, query by ID, update fields, delete (soft via status, hard when unreferenced). Edge operations: create relationships (code-derived-from-code, theme-composed-of-code, interpretation-spans-theme), delete cascading on merge.

Queries: fetch by type and tag, list descendants, fetch semantic neighborhood, retrieve full evidence chain from interpretation to exemplar.

## Integration

- Used by `@src/python/ontology/AGENTS.md` for constraint validation and structure enforcement
- Used by `@src/python/persistence/AGENTS.md` for DuckDB schema and I/O
- Used by `@src/python/hitl/AGENTS.md` for mutation persistence
- Provides traversal data to `@src/python/semantic/AGENTS.md` for ontology-aware retrieval

## Constraints

All modifications must respect ADR-013 constraints. Node operations may invalidate caches. Edge types are limited to defined set: parent-child, contains, derived-from, composed-of, spans, neighbor.

## Documentation

Full node/edge schemas: `@docs/feature/graph-data-model.md`
Dual representation and caching: `@docs/feature/graph-dual-representation.md`
Integration and constraints: `@docs/feature/graph-integration-constraints.md`
Retrieval and evolution: `@docs/feature/graph-retrieval-evolution.md`
Usage examples and performance: `@docs/feature/graph-usage-performance.md`

---

## Implementation Notes — Feature 11 (Refactored)

The networkx graph module is split into three focused files (<100 LOC each):

- **`singleton.py`** — manages the in-memory graph lifecycle.
  - Global `_graph: Optional[nx.DiGraph] = None`.
  - `get_graph(db_path)` — lazy initialization; calls `builder.build_graph(con)` on first access; caches and returns singleton.
  - `rebuild_graph(db_path)` — clears cache, rebuilds fresh graph, replaces singleton.
  - Logs node/edge counts on build/rebuild.

- **`builder.py`** — pure graph construction.
  - `build_graph(con)` — queries all nodes and edges from DuckDB; populates NetworkX `DiGraph`.
  - Node attributes: `type`, `name`, `definition`, `tag`, `status`.
  - Edge attributes: `type`, `metadata` (deserialized from `metadata_json`; falls back to raw string on JSON error).
  - Error handling: catches `duckdb.Error`, logs, raises `RuntimeError`.
  - Helper: `_parse_metadata()`.

- **`sync.py`** — explicit post-mutation synchronization.
  - `sync_node(node_id, db_path)` — fetches node row from `nodes` table, upserts into in-memory graph via `G.add_node()`. Logs warnings for missing nodes; errors logged, not raised.
  - `sync_edge(source_id, target_id, edge_type, db_path)` — fetches edge row from `edges` table by composite key, upserts via `G.add_edge()`. Handles metadata deserialization with fallback.
  - Both use `get_graph(db_path)` to ensure graph initialized, then direct DuckDB connection via `get_connection`.

Public API (re-exported via `__init__.py`):
- `get_graph`, `rebuild_graph`, `sync_node`, `sync_edge`, `build_graph` (available for testing/advanced use).

Entry points for downstream layers:
- `from graph import get_graph` — primary accessor for traversal/query.
- `from graph import sync_node, sync_edge` — called by mutation handlers.
- `build_graph` may be invoked directly in specialized scenarios (e.g., alternate DB path, testing fixtures).

Performance target: <5 seconds to build 10,000 nodes (bulk fetch + batch insert). Verified by unit test.

---

## Implementation Notes — Feature 16 (Transactions)

- **`transactions.py`** — atomic batch operations across DuckDB and NetworkX.
  - `graph_transaction` context manager: enters DuckDB `BEGIN TRANSACTION`, deep-copies the NetworkX graph, sets `_active_tx_conn` ContextVar.
  - On success exit: `COMMIT`; NetworkX changes kept.
  - On error exit: `ROLLBACK`; singleton graph restored from snapshot; traversal cache cleared.
  - Nested transactions raise `GraphTransactionError` (single-level only).
  - Deadlock handling: retry commit once on `duckdb.Error` containing "lock".
  - `get_active_connection()` and `is_in_transaction()` query functions used by CRUD modules.

- **Integration with CRUD**: `create_node`, `create_edge`, `create_edges` check `is_in_transaction()` before opening their own connection. Inside a transaction they use the shared connection and skip connection close / inner transaction boundaries.
