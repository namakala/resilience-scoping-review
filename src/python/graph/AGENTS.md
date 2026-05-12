---
title: "Graph Module"
description: "Low-level graph database operations, node/edge CRUD, and DuckDB persistence layer"
updated_at: "2026-05-11"
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
