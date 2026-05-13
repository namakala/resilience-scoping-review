---
title: "Ontology & Graph Layer"
description: "Represents hierarchical tag ontology, enforces constraints, caches traversal"
updated_at: "2026-05-11"
---

# Ontology & Graph Layer

Manages hierarchical tag namespace, enforces semantic constraints, and accelerates graph queries through materialized traversal caches.

## Purpose

Provide explicit ontology structure for the thematic analysis system. Tags form an immutable directed acyclic graph (DAG) defining semantic hierarchy. Traversal enables interpretation aggregation across branches. Constraints enforce well-formed ontology evolution.

## Core Responsibilities

- Load tag hierarchy from CSV and construct NetworkX DAG
- Represent codes, themes, interpretations as typed graph nodes
- Enforce ADR-013 constraint rules (one-theme-per-code, single-tag-per-theme, etc.)
- Materialize and maintain traversal caches (ancestors, descendants, subtree aggregates)
- Validate ontology mutations (no cycles, referential integrity)
- Support scope-restricted retrieval by tag subtree

## Tag Ontology (ADR-003)

Tags are hierarchical namespaced identifiers: `Problem`, `Problem.Cause`, `Problem.Scope.Association`. DAG structure allows multiple inheritance in principle but typical use is single-parent trees.

Tags are immutable after initial load. They provide context for code assignment and theme aggregation. Descendant tags inherit semantic meaning from ancestors.

Traversal operations: parent, children, ancestors, descendants, subtree induced graph, shortest path, depth.

## Node Types (ADR-004)

Four node types stored in graph database:

**Tags** — Immutable. Define ontology namespace. Fields: tag string, description, depth.

**Codes** — Mutable. Generated from exemplars. Fields: name, definition, parent tag, exemplar_ids, status (draft/approved/merged/rejected), evolved_from chain.

**Themes** — Mutable. Group codes. Fields: name, narrative, parent tag, code_ids, status, evolved_from.

**Interpretations** — Mutable. Aggregate across tags. Fields: name, narrative, theme_ids, tag_spans (set of tags touched), status.

## Edge Types (ADR-004)

Graph edges encode semantic relationships:

- `parent-child` (Tag → Tag): hierarchical containment
- `contains` (Code → Exemplar): evidence linkage
- `derived-from` (Code → Code, Theme → Theme, Interpretation → Interpretation): evolution chain for tracking revisions
- `composed-of` (Theme → Code): aggregation relationship
- `spans` (Interpretation → Theme): semantic coverage across tags
- `neighbor` (Code ↔ Code): optional similarity link for review context

## Constraint Validation (ADR-013)

Validator enforces structural invariants:

- Code belongs to exactly one theme (upon review approval)
- Theme contains multiple codes but all within same parent tag
- Theme belongs to exactly one interpretation
- Interpretation may span multiple tags (contiguous subtree only)
- Tag assignments must exist in ontology
- No cycles introduced through merges

Constraint violations block persistence and trigger error messages for user correction.

## Traversal Caching (ADR-012)

Repeated subtree traversals during interpretation synthesis are expensive. This module materializes commonly used traversal results:

- Ancestor sets for every tag
- Descendant sets for every tag
- Aggregated exemplar_ids in subtree
- Aggregated code_ids in subtree
- Aggregated theme_ids in subtree

Caches stored as JSON arrays in DuckDB. Incrementally invalidated when tags merge or exemplar assignments change.

## Integration

Provides graph and validation services to:

- `@src/python/persistence/AGENTS.md` (node/edge persistence API)
- `@src/python/semantic/AGENTS.md` (subtree scoping for retrieval)
- `@src/python/inference/AGENTS.md` (ontology context for prompt templates)
- `@src/python/hitl/AGENTS.md` (constraint checking before mutation)
- `@src/python/pipeline/AGENTS.md` (traversal inputs to DAG nodes)

## Data Storage

Nodes and edges stored in DuckDB tables with primary key constraints. In-memory NetworkX copy constructed at startup for fast traversal operations. Changes propagated to both representations synchronously.

Full node/edge schemas: `@docs/feature/graph-data-model.md`
