---
title: "Hybrid Retrieval Sub-package"
description: "Four-stage retrieval: scope -> BM25 -> embeddings -> rerank with proximity"
updated_at: "2026-05-13"
---

# Hybrid Retrieval Package

Implements ADR-006 hybrid retrieval pipeline. Split into four focused
modules, each under 80 lines.

## Modules

- **api.py** — Public `hybrid_retrieve()` orchestrator. Calls scope
  resolution, BM25 scoring, embedding scoring, then reranks via
  weighted formula with proximity boost. Also contains private
  `_score_bm25_or_default()` and `_rerank()` helpers.

- **candidates.py** — `resolve_candidate_ids()` maps ontology subtree
  to entity IDs. Uses traversal cache for exemplars; queries DuckDB
  nodes table for codes/themes/interpretations.

- **scoring.py** — Scoring functions: `get_bm25_scores_for_candidates()`,
  `get_embedding_scores()`, and `get_depth()` for ontology proximity.
  Each independently testable.

- **weights.py** — `WeightConfig` namedtuple and `select_weights()`
  returning the appropriate weight triplet for exemplar vs non-exemplar
  candidate types.

## Public API

Re-exported from `__init__.py`: `hybrid_retrieve()`. Existing imports
at `semantic.retrieval` and `semantic` remain unchanged.
