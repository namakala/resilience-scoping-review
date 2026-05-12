---
title: "53 — node-function-definitions"
description: "50+ pure node functions for artifacts, embedding, retrieval, inference, review, export"
updated_at: "2026-05-12"
phase: 9
---

# Feature 53: node-function-definitions


---

## Description

Each node is a pure function decorated with `@hub.operator`. Inputs explicit as function parameters; outputs dataframes/objects. No side effects (persistence, print, user I/O outside). Define 50+ node functions covering artifact loading, embedding, index building, retrieval, inference, review orchestration, and export.

---

## Acceptance Criteria

- Every node function has type hints on all parameters and return type
- Functions deterministic: same inputs → same outputs
- Side effects isolated: node calls persistence layer via injected clients
- Unit test per node: given fixture input, output matches expected
- Nodes grouped logically in modules: `nodes/artifact.py`, `nodes/embedding.py`, `nodes/retrieval.py`, `nodes/inference.py`, `nodes/review.py`, `nodes/export.py`

---

## Dependencies

@docs/plan/52-dag-constructor.md

---

## Implementation Notes

- Module: `src/python/pipeline/nodes/` (multiple files)
- Example node signature:
  ```python
  def embed_exemplars(exemplars: pl.LazyFrame, model: SentenceTransformer) -> pl.LazyFrame:
      """Add embedding column to exemplars LazyFrame."""
  ```
- Config injected: `config: Config`
- Return types: `pl.LazyFrame`, `dict`, `list`, `hamilton.DAG` nodes, `None`
- Each node pure: no DB writes or prints; reads only from inputs and read-only caches

---

**References:** ADR-008
