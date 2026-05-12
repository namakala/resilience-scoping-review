---
title: "Persistence & Storage Layer"
description: "Handles artifact serialization, caching, and session state management"
updated_at: "2026-05-11"
---

# Persistence & Storage Layer

Manages all disk I/O: immutable artifacts, mutable graph, embedding cache, session state. Abstracts storage format behind read/write interfaces.

## Purpose

Durable storage and efficient retrieval of all data artifacts. Isolate storage concerns from computation layers. Provide caching with content-aware invalidation.

## Core Responsibilities

- Serialize and deserialize exemplars, keywords, tag ontology as Parquet
- Persist mutable graph nodes and edges in DuckDB
- Manage embedding cache with content-hash invalidation
- Serialize BM25 index for reuse
- Save and restore workflow state for checkpoint/resume
- Validate data integrity on load (schema, uniqueness, parent references)

## Immutable Artifacts (ADR-002)

Exemplars, keywords, ontology written once, never updated. Parquet for columnar efficiency. Polars lazy evaluation. Loaded once; cached in memory.

Immutable schemas:

- Exemplars: id, document, tag, content, keywords, content_hash
- Keywords: keyword_id, exemplar_id, keyword_text, frequency
- Ontology: tag, parent, description, depth

## Mutable Semantics

Codes, themes, interpretations stored in DuckDB with vertices and edges. NetworkX in-memory mirror for traversal. Changes written transactionally.

Nodes: id, type (code/theme/interpretation), name, definition, tag, status, data_json, timestamps.
Edges: source_id, target_id, edge_type, metadata_json.

Traversal caches stored as JSON arrays. Materialized for common queries (ancestors, descendants, subtree aggregates).

## Embedding Cache (ADR-005)

Keyed by (entity_id, entity_type). Stores: embedding vector, model_hash, content_hash, timestamp.

Lookup returns cache only if model and content hashes match. Put upserts. Invalidate deletes specific entry. Cache regenerated when entity definition changes or model updates.

## BM25 Index

Serialized with pickle. Contains: corpus (keyword strings), BM25 object, entity map. Rebuild only on keyword changes.

## Session State

Workflow progress in `output/session.duckdb`: current_stage, dirty_flags per tag, user_action_log, checkpoints. Enables resume after crash.

## Directory Layout

Immutable inputs in `data/raw/`: user-provided CSV files. Processed artifacts in `data/processed/`: Parquet caches and DuckDB graph. Session outputs in `data/output/`: state database, results JSON, logs.

## Validation

On load: required columns present, no duplicate IDs, parent tags exist in ontology, referential integrity for edges.

## Module Structure

The persistence layer is organized into focused modules:

- **`converter.py`** (135 lines) — Orchestrator: `CSVToParquetConverter` class and `convert_csvs` convenience function. Coordinates reading, validation, enrichment, and writing.
- **`reader.py`** (201 lines) — CSV ingestion: schema validation, data quality checks, content_hash enrichment, tag reconciliation. Pure functions.
- **`writer.py`** (61 lines) — Parquet serialization: write LazyFrames to Parquet, compute compression statistics.
- **`exceptions.py`** (17 lines) — Exception hierarchy: `ConversionError`, `SchemaValidationError`, `DataQualityError`.
- **`graph.py`** — (separate module) DuckDB graph persistence for codes, themes, interpretations.
- **`cache.py`** — (planned) Embedding cache with content-hash invalidation.
- **`state.py`** — (planned) Session state checkpoint and resume.

Total converter-related modules: 414 lines across 4 files. Each file is independently sized under the 300-line limit, with reader.py being the largest at 201 lines but still within acceptable range given its cohesive responsibilities.

## Public API

All symbols exported from `persistence.converter`:
```python
from persistence.converter import (
    CSVToParquetConverter,
    convert_csvs,
    ConversionError,
    SchemaValidationError,
    DataQualityError,
)
```

The refactored module maintains 100% backward compatibility; existing imports from `converter.py` remain valid.

## Public API

All symbols exported from `persistence.converter`:
```python
from persistence.converter import (
    CSVToParquetConverter,
    convert_csvs,
    ConversionError,
    SchemaValidationError,
    DataQualityError,
)
```

The refactored module maintains 100% backward compatibility; existing imports from `converter.py` remain valid.
