---
title: "71 — dynamic-fewshot-retrieval"
description: "Replace static few-shot pool with dynamic retrieval from approved artifacts"
updated_at: "2026-05-14"
phase: 12
---

# Feature 71: dynamic-fewshot-retrieval

## Description

Replace the static curated JSON files in `src/python/inference/fewshot/`
with dynamic retrieval from previously HITL-approved codes, themes, and
interpretations. The same `load_fewshot()` interface should work with
both backends.

## Motivation

Static examples are manually curated and may become outdated or
domain-mismatched as the ontology grows. Dynamic retrieval selects
the most semantically similar exemplar-code pair for each batch,
improving relevance and output quality.

## Prerequisites

- Phase 6 (Code Inference & Review) complete — approved codes exist
  in the graph database
- Phase 7 (Theme Inference & Review) complete — approved themes exist
- Phase 8 (Interpretation Synthesis & Review) complete — approved
  interpretations exist
- At least ~50 approved pairs per stage for a meaningful corpus

## Design

### Corpus

Store approved `(exemplar, code)` pairs as retrievable documents in
DuckDB. Each document includes:
- The rendered user prompt text (input)
- The approved code output (output)
- Embedding vector of input text (for similarity search)
- Tag path, timestamp, and approval metadata

### Selection

For a new inference batch:
1. Render the user prompt for the current batch (as normal)
2. Compute its embedding vector
3. Query the approved-pair corpus via cosine similarity
4. Return the top-*N* most similar `{"user": ..., "assistant": ...}`
   pairs
5. Fall back to static pool if corpus has fewer than *N* matches

The hybrid retrieval engine (plan `28-hybrid-retrieval-engine.md`)
already supports BM25 + embedding fusion — reuse it if feasible.

### Drop-in Replacement

```python
# Before (static):
examples = load_fewshot("code_inference", count=2)

# After (dynamic):
examples = load_fewshot(
    "code_inference", count=2,
    query=current_batch_user_prompt,   # new kwarg
)
```

The static loader ignores the `query` kwarg. The dynamic loader uses
it. Call sites pass the rendered user prompt when available.

### Steps

1. Add `query: str | None = None` parameter to `load_fewshot()`
   (backward-compatible default)
2. Create `ApprovedPairStore` in the persistence layer with CRUD for
   approved exemplar-code pairs
3. Create `DynamicFewShotSelector` that queries the store by embedding
   similarity
4. Wire into the inference services next to the static loader
5. Add config toggle `FEWSHOT_SOURCE` (values: `static`, `dynamic`,
   `hybrid`)

### Files

| File | Action |
|---|---|
| `src/python/inference/fewshot_loader.py` | Add `query` param |
| `src/python/persistence/approved_pair_store.py` | **Create** — DuckDB table and CRUD |
| `src/python/inference/dynamic_fewshot.py` | **Create** — embedding-based selector |
| `src/python/config/settings.py` | Add `FEWSHOT_SOURCE` |
| `.env.example` | Document `FEWSHOT_SOURCE` |

## Acceptance Criteria

- Given approved pairs in the store, `load_fewshot()` with `query`
  returns relevant examples
- Given empty store, falls back to static pool or returns `[]`
- Adding a new approved pair makes it available for future selection
- Performance: retrieval adds <100ms per inference call

## References

- ADR-005 (Embeddings for retrieval)
- ADR-006 (Hybrid ranking: BM25 + cosine + ontology proximity)
- Plan `28-hybrid-retrieval-engine.md`
