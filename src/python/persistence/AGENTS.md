---
title: "Persistence & Storage Layer"
description: "Handles artifact serialization, caching, and session state management"
updated_at: "2026-05-12"
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

Immutable inputs in `data/raw/`: user-provided CSV files. Processed artifacts in `data/processed/` (configurable via `PROCESSED_DATA_PATH` environment variable): Parquet caches and DuckDB graph. Session outputs in `data/output/`: state database, results JSON, logs.

## Configuration

- **`PROCESSED_DATA_PATH`** — Base directory for all processed artifacts. Default: `data/processed/`. This includes exemplars.parquet, tags.parquet, keywords.parquet, the BM25 index, and any intermediate outputs. Set via environment variable to relocate processed data to alternative storage.

## Validation

On load: required columns present, no duplicate IDs, parent tags exist in ontology, referential integrity for edges.

## Module Structure

The persistence layer is organized into focused modules:

- **`converter.py`** — Orchestrator: `CSVToParquetConverter` class and `convert_csvs` convenience function. Coordinates reading, validation, enrichment, and writing.
- **`reader.py`** — CSV ingestion: schema validation, data quality checks, content_hash enrichment, tag reconciliation. Pure functions.
- **`writer.py`** — Parquet serialization: write LazyFrames to Parquet, compute compression statistics.
- **`exceptions.py`** — Exception hierarchy: `ConversionError`, `SchemaValidationError`, `DataQualityError`.
- **`duckdb_connection.py`** — Connection lifecycle: `get_connection()`, schema version getter/setter, DEFAULT_DB_PATH, SCHEMA_VERSION.
- **`duckdb_schema.py`** — Table DDL definitions: `_create_nodes_table()`, `_create_edges_table()`, `_create_traversal_cache_table()`, `_create_session_state_table()`, `_create_user_actions_table()`, `_create_embedding_cache_table()`, `_ensure_sequences()`.
- **`duckdb_migrations.py`** — Migration engine: `migrate_schema()`, `_apply_migration()`, version progression logic.
- **`duckdb_init.py`** — Orchestrator: `initialize_database()`, `init_or_migrate()`. Coordinates connection, migrations, and schema creation.
 - **`hash_utils.py`** — Hash computation utilities: `compute_model_hash()`. Produces deterministic model fingerprints for cache validation.
 - **`embedding_cache.py`** — CRUD operations: `get_embedding()`, `put_embedding()`, `invalidate_entity()`, `invalidate_by_content_hash()`. Handles NumPy serialization and content-hash invalidation.
 - **`cache_analytics.py`** — Cache statistics: `get_cache_stats()`. Provides aggregate metrics and monitoring queries.
