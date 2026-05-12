---
title: "32 — batch-grouping-by-tag"
description: "Group exemplars/codes/themes by parent tag into batches ≤15"
updated_at: "2026-05-12"
phase: 5
---

# Feature 32: batch-grouping-by-tag


---

## Description

Before LLM inference, group items by their parent tag. For code inference: group exemplars by `tag` field; each batch ≤15 exemplars. For theme inference: group approved codes by their `tag` (theme inference only within a single tag). For interpretation: group themes by tag-span combination (themes from multiple tags batched together). Each batch tagged with batch_id (e.g., `code_tag_Problem.Cause_batch_01`).

---

## Acceptance Criteria

- Batcher function `group_by_tag(items: list, max_per_batch: int) → list[Batch]`
- Total batch count logged: `N batches prepared for tag X`
- Batches preserve order within tag (by ID)
- If a tag has >15 exemplars, split into multiple batches of 15,14,... (last may be smaller)
- Batch metadata includes: `tag`, `batch_index`, `total_batches`, `item_count`
- Empty tags skipped

---

## Dependencies

@docs/plan/06-artifact-loaders.md

---

## Implementation Notes

- Module: `src/python/inference/batching.py`
- `Batch` dataclass: `tag: str, items: list, batch_index: int, total_batches: int`
- Group: `items_by_tag = defaultdict(list); for item in items: items_by_tag[item.tag].append(item)`
- Split each tag's list into chunks of `max_per_batch`
- Return flat list of `Batch` objects
- Logging: `logger.info("Prepared %d batches for tag %s", len(batches), tag)`

---

**References:** ADR-010
