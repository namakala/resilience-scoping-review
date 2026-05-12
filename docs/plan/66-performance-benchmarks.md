---
title: "66 — performance-benchmarks"
description: "Benchmark suite: embedding, BM25, retrieval, memory; regression thresholds"
updated_at: "2026-05-12"
phase: 11
---

# Feature 66: performance-benchmarks


---

## Description

Run performance suite on standard laptop (8GB RAM, Intel i5 equivalent):
- Embedding generation: 1000 exemplars
- BM25 index build: 1000 exemplars
- Retrieval: 1000 candidates, 5 query keywords
- LLM batch: simulated (measure overhead only)
Report times and memory usage.

---

## Acceptance Criteria

- Embedding 1000 exemplars <2min
- BM25 build <1min
- Retrieval (hybrid) <200ms per query
- Memory peak <4 GB during full run
- Benchmarks logged to `data/output/benchmarks.json`
- Regression threshold: if any metric degrades >20%, CI warns

---

## Dependencies

@docs/plan/65-end-to-end-workflow-test.md

---

## Implementation Notes

- Module: `tests/performance/benchmark_suite.py` or `scripts/benchmarks.py`
- Use `time.perf_counter()` for timing; `psutil` for memory
- Functions: `benchmark_embedding(n=1000)`, `benchmark_bm25(n=1000)`, `benchmark_retrieval(k=1000)`
- Store results as JSON: `{"embedding_1000": {"seconds": 120.5, "memory_mb": 256}, ...}`
- CI comparison: read previous `benchmarks.json` from `main` branch; compute delta; fail if >20% slower
- Run on workflow runner with `runner.label == 'performance'` or manually

---

**References:** None
