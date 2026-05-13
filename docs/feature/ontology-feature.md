---
title: "Ontology Layer"
description: "Tag DAG construction, traversal, caching, constraint validation, and scope restriction"
updated_at: 2026-05-13
---

# Ontology Layer

The ontology layer manages the hierarchical tag namespace, enforces structural invariants, and accelerates graph queries through materialized caches.

## Purpose & Design Rationale

Tags form an explicit DAG (e.g., `Problem` → `Problem.Cause` → `Problem.Cause.Barrier`). ADR-003 mandates hierarchy not be inferred from embeddings — the ontology DAG provides predictable traversal, inheritance-aware retrieval, and branch-based interpretation aggregation. ADR-012 caches repeated traversals. ADR-013 enforces well-formed thematic relationships.

## Tag DAG Construction

`build_tag_dag()` reads tags from `tags.csv` (tag, parent, description, n_contents) and builds a NetworkX `DiGraph` with edges `parent → child`. Graph-based depth is computed as shortest path from roots (depth 0). Validates all parent references exist (raises `ForeignKeyError`) and the graph is acyclic (raises `CycleError`). Cached as a module-level singleton; `rebuild_tag_dag()` clears and reconstructs.

## Traversal Operations

Functions in `traversal.py` operate on the in-memory DAG:

- `get_ancestors(tag)` — ordered root→parent (excludes tag)
- `get_descendants(tag)` — sorted by depth ascending (excludes tag)
- `get_subtree(tag)` — {tag} ∪ descendants
- `is_ancestor(parent, child)` — O(1) after LRU cache warm-up

Cached with `functools.lru_cache`. `clear_traversal_cache()` must be called after any DAG mutation.

## Materialized Traversal Cache (ADR-012)

The `traversal_cache` DuckDB table precomputes per-tag: ancestors, descendants, subtree_exemplars, subtree_codes, subtree_themes — stored as JSON arrays. Built via `build_traversal_cache()` which iterates all tags, delegates to traversal.py for computation, and persists results.

`get_cached_subtree(tag)` reads from DuckDB with auto-recompute on cache miss or `stale=TRUE`. `invalidate_cache_for_tag(tag)` sets `stale=TRUE` on the tag and all its descendants (cascade), with audit log entries. `invalidate_cache_for_tags(tags)` does bulk invalidation in a single transaction.

## Scope Restriction

`get_scope_for_tag(tag)` returns {tag} ∪ descendants via the traversal cache. Used by the semantic retrieval layer (ADR-006 stage 1) to restrict candidate pools before BM25 and embedding ranking.

## Constraint Validation (ADR-013)

`validate_constraint(entity, action)` dispatches to six rule functions based on action type:

| Rule | Enforced On | What It Checks |
|------|-------------|----------------|
| Code ≤1 approved theme | approve code | No outgoing `composed-of` from an approved theme to this code |
| Theme ≥2 codes, same tag | approve theme | At least 2 codes linked via `composed-of`, all sharing the same `tag` value |
| Theme ≤1 approved interpretation | approve theme | No incoming `spans` from an approved interpretation |
| Interpretation contiguous subtree | approve/create interpretation | `tag_spans` set forms a connected sub-DAG (LCA + shortest-path check, see `contiguity.py`) |
| Tag exists in ontology | all actions | Tag present in the tag DAG |
| No cycles after merge | merge | Graph+proposed edges remain acyclic |

Rules are self-contained functions in `rules.py`; contiguity logic is in `contiguity.py`. Constraints are checked at three points: on write (CRUD API), during HITL review (pre-mutation), and on batch inference (post-LLM).

## File Organization

- `dag.py` — Tag DAG construction, singleton, validation
- `traversal.py` — In-memory traversal (LRU-cached)
- `cache.py` / `cache_io.py` — DuckDB traversal cache build/read
- `invalidation.py` — Stale-flag cascade with audit log
- `constraints.py` — Dispatch + error codes
- `rules.py` — 6 rule implementations
- `contiguity.py` — Subtree contiguity check
- `scope.py` — Scope restriction helper

## Integration

- **Semantic layer** — scope restriction for hybrid retrieval
- **Inference** — ontology context (ancestor path, existing codes) for prompt templates
- **HITL** — pre-mutation constraint validation
- **Pipeline** — traversal cache inputs to DAG nodes
- **Persistence** — graph CRUD operations on DuckDB
