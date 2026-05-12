---
title: "23 — sentence-transformer-initialization"
description: "Load all-MiniLM-L6-v2; generate_embedding() function"
updated_at: "2026-05-12"
phase: 4
---

# Feature 23: sentence-transformer-initialization


---

## Description

Load the `all-MiniLM-L6-v2` sentence-transformer model in CPU-only mode (no CUDA dependencies). Expose `generate_embedding(text: str) → np.ndarray[float32]` of dimension 384. Handle model download and caching under `~/.cache/torch/sentence_transformers`.

---

## Acceptance Criteria

- Model loads in <30 seconds on first run
- `generate_embedding("test")` returns `np.ndarray` with `shape=(384,)` and `dtype=np.float32`
- All vectors L2-normalized to unit length (cosine similarity = dot product)
- CPU-only flag set (`device='cpu'`) to avoid GPU dependency
- Model version hash stored for cache invalidation
- Thread-safe: concurrent calls do not corrupt model state

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

- Module: `src/python/semantic/embeddings.py`
- `model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')`
- Normalize: `emb / np.linalg.norm(emb)`
- Model hash: `hashlib.sha256(model_name.encode()).hexdigest()[:16]`
- Thread-safety: use `threading.Lock()` around model.encode if not inherently thread-safe

---

**References:** ADR-005
