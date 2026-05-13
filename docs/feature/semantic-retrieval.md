---
title: "Semantic Retrieval Layer"
description: "Keyword extraction, BM25 indexing, embedding cache, and hybrid retrieval pipeline"
updated_at: 2026-05-13
---

# Semantic Retrieval Layer

The semantic layer computes embeddings and lexical indices, then executes hybrid retrieval combining semantic similarity, lexical overlap, and ontology proximity.

## Purpose & Design Rationale

ADR-005 mandates embeddings for retrieval only (not for defining hierarchy). ADR-006 adds BM25 lexical search and ontology proximity scoring because embeddings alone cannot capture exact terminology or structural context. Hybrid retrieval prevents semantic drift while preserving hierarchy awareness. Immutable artifacts (exemplars, keywords) anchor the evidence base; mutable entities (codes, themes, interpretations) recompute on content change.

## Keyword Extraction

`extract_keywords()` runs KeyBERT with MMR diversity (top-5, diversity=0.5, 1–2 ngrams) on each exemplar's content. Uses the same `all-MiniLM-L6-v2` model as the embedding layer — no additional download. Results are written to `keywords.parquet` as an immutable, one-shot artifact. Guarded by existence check; `force_rebuild=True` to re-run.

## BM25 Lexical Index

`build_index()` trains `rank_bm25.BM25Okapi` on the tokenized keyword corpus. Corpus constructed by grouping keywords per exemplar, sorting alphabetically, and applying the configured tokenizer pipeline.

**Tokenizer** (`tokenizer.py`): configurable via `BM25_TOKENIZER_CONFIG` env var. Toggles (applied in order): `lowercase`, `strip_punctuation`, `split_by_space` (required), `remove_stopword`. Default: `lowercase,split_by_space`.

**Persistence** (`persistence.py`): index serialized to pickle at `data/processed/bm25_index.pkl`. Atomic write via temporary file + rename + round-trip sanity check. `corpus_hash` (first 16 hex chars of SHA256 over concatenated sorted keyword strings) stored in metadata and validated on load to detect staleness.

`get_scores(query)` returns exemplar→score dict with min-max normalization to [0, 1]. `get_top_n(query, n=50)` returns top-N sorted descending.

## Embedding Model & Cache

Model: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, CPU-only. Lazy-loaded thread-safe singleton with double-checked locking. Cache location configurable via `MODEL_CACHE_DIR` (default `~/.cache/huggingface/hub/`).

**Immutable embeddings** (exemplars, keywords): generated once via `generate_exemplar_embeddings()` / `generate_keyword_embeddings()`. Cached indefinitely under content-hash key in the DuckDB `embedding_cache` table.

**Mutable embeddings** (codes, themes, interpretations): recomputed only when definition text changes. Stale embeddings flagged via dirty-state propagation in the pipeline.

All embeddings encode full context: entity name, definition, supporting evidence, and ontology path. Batch encoding with progress bars and configurable batch size (default 32).

## Hybrid Retrieval Pipeline (ADR-006)

`hybrid_retrieve()` executes four stages:

1. **Scope restriction** — Resolve candidate entity IDs within `query_tag`'s ontology subtree via `resolve_candidate_ids()`. Exemplars use the traversal cache; other types query the DuckDB `nodes` table.
2. **BM25 retrieval** — Score candidates by lexical match. For exemplar type only (non-exemplar types renormalize weights to drop BM25).
3. **Embedding retrieval** — Cosine similarity via cached L2-normalized embeddings. Dot product = cosine since vectors are unit.
4. **Rerank** — Weighted sum: `w.emb × sim + w.prox × 1/(1+Δdepth) + w.bm25 × bm25_score`.

Weights: exemplars → emb=0.5, prox=0.3, bm25=0.2. Non-exemplars → emb=0.625, prox=0.375, bm25=0.0 (renormalized). Returns `[(entity_id, score)]` sorted descending, top-k (default 50).

Weights are configurable per use case via `WeightConfig` in `weights.py`.

## Neighbor Discovery

`find_neighbors()` finds k-nearest neighbors by embedding similarity within the same tag scope. Used by HITL review to suggest similar codes. Computes cosine similarity against all same-type candidates in the ontology subtree. Filters to similarity ≥ 0.5. Results cached in-memory with 5-minute TTL to avoid recomputation during interactive sessions.

## Similarity Matrix

`compute_similarity(entity_ids, entity_type)` computes pairwise cosine similarity via dot product on the stacked (n, 384) embedding matrix. Diagonal explicitly set to 1.0 to correct numerical drift. Used for clustering and review context. Raises `CacheMissError` if any entity lacks a cached embedding.

## File Organization

- `embeddings.py` — Model singleton, generate_embedding/batch, cache lifecycle
- `embedding_generation.py` — Exemplar batch encoding with content-hash dedup
- `keyword_embedding.py` — Keyword batch encoding
- `keyword_extraction.py` — KeyBERT keyword extraction
- `tokenizer.py` — Configurable tokenization pipeline
- `corpus.py` — Corpus construction and hash computation
- `index_builder.py` — BM25 index training and serialization
- `persistence.py` — Pickle save/load with atomic write + round-trip check
- `cache.py` — In-memory BM25 index cache
- `api.py` — Public scoring API (get_scores, get_top_n, get_index_info)
- `neighbors.py` — k-NN discovery with TTL cache
- `similarity.py` — Pairwise cosine similarity matrix
- `retrieval/` — Hybrid retrieval sub-package (api.py, candidates.py, scoring.py, weights.py)
- `exceptions.py` — BM25IndexError, IndexCorruptedError, CacheMissError

## Integration

- **Inference** — retrieve relevant exemplars (code inference), similar codes (theme inference), candidate themes (interpretation synthesis)
- **HITL** — neighbor suggestions during code review
- **Pipeline** — DAG nodes for embedding generation and retrieval
- **Ontology layer** — scope restriction via traversal cache
