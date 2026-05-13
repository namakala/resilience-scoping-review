---
title: "23 — sentence-transformer-initialization"
description: "Load all-MiniLM-L6-v2; generate_embedding() function with cache management"
updated_at: "2026-05-13"
phase: 4
---

# Feature 23: sentence-transformer-initialization

---

## Description

Load the `sentence-transformers/all-MiniLM-L6-v2` model in CPU-only mode (no CUDA dependencies). Expose `generate_embedding(text: str) → np.ndarray[float32]` of dimension 384, plus cache management functions (`clear_model_cache`, `reload_model`). Model download and caching under `~/.cache/huggingface/hub/` (configurable via `MODEL_CACHE_DIR` env var).

---

## Acceptance Criteria

- Model loads in <30 seconds on first run
- `generate_embedding("test")` returns `np.ndarray` with `shape=(384,)` and `dtype=np.float32`
- All vectors L2-normalized to unit length (cosine similarity = dot product)
- CPU-only flag set (`device='cpu'`) to avoid GPU dependency
- Model version hash stored for cache invalidation (`compute_model_hash`)
- Thread-safe: concurrent calls do not corrupt model state (uses `threading.Lock()`)
- `clear_model_cache()` removes cached model from disk and resets singleton
- `reload_model(clear_cache=False)` resets singleton; `clear_cache=True` also wipes disk cache

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

- Module: `src/python/semantic/embeddings.py`
- `model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu', cache_folder=str(MODEL_CACHE_DIR))`
- Normalize: pass `normalize_embeddings=True` to `model.encode()`
- Model hash: reuse `persistence.hash_utils.compute_model_hash()`
- Thread-safety: use `threading.Lock()` around model.encode
- MODEL_CACHE_DIR defaults to `~/.cache/huggingface/hub/`, overridable via `MODEL_CACHE_DIR` env var
- Cache management: `clear_model_cache()` removes `{MODEL_CACHE_DIR}/models--sentence-transformers--all-MiniLM-L6-v2/` with `shutil.rmtree`
- `reload_model()` resets singleton to None; lazy re-download on next `generate_embedding()` call
- Lazy import of `SentenceTransformer` inside `_get_model()` for fast module import

---

**References:** ADR-005
