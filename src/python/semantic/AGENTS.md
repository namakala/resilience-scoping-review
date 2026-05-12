---
title: "Semantic Retrieval Layer"
description: "Manages embeddings, lexical indexing, and hybrid semantic search"
updated_at: "2026-05-11"
---

# Semantic Retrieval Layer

Computes vector embeddings and lexical indices. Performs hybrid retrieval combining semantic similarity, lexical overlap, and ontology proximity.

## Purpose

Retrieve semantically relevant exemplars, codes, themes, and interpretations across the analysis pipeline. Provide consistent similarity scoring for code assignment, theme grouping, and interpretation synthesis.

## Core Responsibilities

- Generate sentence-transformer embeddings for all semantic entities
- Build BM25 lexical index over extracted keywords
- Execute hybrid retrieval: scope restriction → BM25 → embeddings → reranking
- Cache embeddings with content-hash invalidation
- Compute similarity matrices for neighboring entity discovery

## Embedding Strategy (ADR-005)

Two embedding classes:

**Immutable embeddings** stored once and never regenerated: exemplars and extracted keywords. These anchor the semantic evidence base. Cached indefinitely under content hash.

**Mutable embeddings** for evolving semantics: codes, themes, interpretations. Recomputed only when definition text changes. Stored alongside metadata; stale embeddings flagged via dirty-state propagation.

All embeddings encode full context: entity name, definition, supporting evidence, and ontology path. This improves semantic matching during retrieval.

## BM25 Lexical Index (ADR-006)

Complementary lexical guardrail. BM25 captures exact term overlap and keyword consistency. Prevents semantic drift from embeddings alone. Index built once on keyword corpus; stored as serialized object. Does not update incrementally — rebuild if keyword set changes.

Returns document-level relevance scores normalized to [0, 1].

## Hybrid Retrieval Pipeline

Four-stage ranking:

1. **Graph scope** — Restrict candidates to ontology subtree (tag + descendants)
2. **BM25 retrieval** — Retrieve top-50 by lexical score
3. **Embedding retrieval** — Retrieve top-50 by cosine similarity
4. **Rerank** — Compute weighted sum of BM25 score, embedding cosine, and graph proximity penalty

Weights: embeddings (0.5), proximity (0.3), BM25 (0.2). Adjustable per use case. Final ranking sorted descending by combined score.

## Caching & Performance

Embedding cache uses Parquet with columns: entity_id, entity_type, embedding array, model_hash, content_hash, timestamp. Lookup by (entity_id, type). Regenerate only when content_hash mismatches or model version changes.

Memory footprint: 1,000 exemplars at 384 dimensions occupies ~1.5 MB. Query latency: ~10 ms per retrieval. Suitable for laptop execution.

## Integration

Serves all inference stages:

- Code inference: retrieve relevant exemplars by tag and query keywords
- Theme inference: retrieve similar codes within a tag
- Interpretation synthesis: retrieve candidate themes across tag branches

Also used by HITL review to suggest semantic neighbors for codes.

## Constraints

Embedding model fixed at `all-MiniLM-L6-v2` (384 dimensions, CPU-friendly). All retrieval queries must respect tag-based scope unless context requires full-ontology search. Top-k results always sorted descending.

## References

Implements ADR-005 (Embedding Strategy) and ADR-006 (Retrieval Strategy). See `@ADR.md` for full rationale.
