---
title: "56 — selective-execution"
description: "dag.execute() runs only dirty or required nodes"
updated_at: "2026-05-12"
phase: 9
---

# Feature 56: selective-execution


---

## Description

`dag.execute(inputs, overrides={})` runs only dirty or explicitly required nodes. Hamilton's built-in caching combined with custom dirty-flags. Execution plan pruned to minimal set.

---

## Acceptance Criteria

- After edit, `executor.execute()` runs only affected nodes (verified via node execution logs)
- Performance: edit one code → pipeline completes in <30s (vs full run 10min)
- Initial full run populates all caches; subsequent runs fast
- Explicit `--stage N` resume starts from current_stage (dirty flags from prior stage)
- Cache hit rate >90% after initial run

---

## Dependencies

@docs/plan/55-dirty-flag-propagation.md

---

## Implementation Notes

- Module: `src/python/pipeline/executor.py`
- `executor = dag.driver()`; use `result = executor.execute(..., overrides=...)`
- Custom cache: `@cachable(cache_id="node_cache", ...)` with `cache_key` including entity version hash
- On execute: log each node "START" and "FINISH"; collect duration
- Selective: before running node, check `if node.output_valid_and_cached(): skip`
- `overrides` replace node output (e.g., mock LLM in tests)
- `--stage N` implemented as override: `overrides={'current_stage': N}`

---

**References:** ADR-008, ADR-007
