---
title: "08 — embedding-cache-schema"
description: "DuckDB table for embedding cache with content_hash invalidation"
updated_at: "2026-05-12"
phase: 1
---

# Feature 08: embedding-cache-schema


---

## Description

Add DuckDB table `embedding_cache` with schema: `entity_id VARCHAR, entity_type VARCHAR (enum: exemplar,keyword,code,theme,interpretation), embedding BLOB (float32 array serialized), model_hash VARCHAR, content_hash VARCHAR, timestamp TIMESTAMP`. Primary key `(entity_id, entity_type)`.

---

## Acceptance Criteria

- Table created with specified schema
- Insertion accepts NumPy array (converted to bytes via `.tobytes()`)
- Query by `(entity_id, entity_type)` returns deserialized NumPy array
- Index on `content_hash` for cache invalidation scans
- `model_hash` stores fingerprint of embedding model version (e.g., "all-MiniLM-L6-v2-v1")
- Cache hit rate can be queried via SQL

---

## Dependencies

@docs/plan/07-duckdb-schema-init.md

---

## Implementation Notes

- Module: `src/python/persistence/embedding_cache.py`
- Serialize: `np_array.astype('float32').tobytes()`
- Deserialize: `np.frombuffer(blob, dtype='float32')`
- `model_hash` = `hashlib.sha256(model_name.encode()).hexdigest()[:16]`
- Query hit rate: `SELECT COUNT(*) FROM embedding_cache WHERE ...` vs attempts

---

**References:** ADR-005 (Embedding Strategy)
