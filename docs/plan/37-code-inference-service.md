---
title: "37 — code-inference-service"
description: "Batch LLM call per tag to generate one code per exemplar"
updated_at: "2026-05-12"
phase: 6
---

# Feature 37: code-inference-service


---

## Description

For each tag with pending exemplars, prepare batch using `code_inference.j2`. Include: tag name, ancestors list, tag description, list of existing codes (name+definition) for context, and up to 15 exemplars each with `id, content, keywords`. Call Groq with temperature=0.3 for consistency. Parse responses with `CodeInference` schema.

---

## Acceptance Criteria

- Every exemplar in batch receives at least one code candidate
- LLM instructed to generate exactly one code per exemplar (enforced by prompt and validation)
- Duplicate code names within same tag flagged and merged later
- Supporting quote extracted verbatim from exemplar content (≤200 chars)
- `related_existing_codes` lists code names that are semantically similar (for later merge suggestions)
- Service returns list of `CodeInference` items; failures logged with exemplar_id for manual retry
- Throughput: ≥10 exemplars/sec (batch of 15 ≈ 1.5s)

---

## Dependencies

@docs/plan/32-batch-grouping-by-tag.md
@docs/plan/33-structured-output-parser.md

---

## Implementation Notes

- Module: `src/python/inference/code_inference.py`
- For each tag, get pending exemplars via `get_pending_items(stage='code', tag=tag)`
- Prepare batch: list of exemplars with metadata; call `prompt_template.render(exemplars=...)`
- Call Groq: `response = await client.chat.completions.create(model=..., messages=[...], response_format={"type": "json_object"}, temperature=0.3)`
- Parse: `parsed = parse_llm_json(response.choices[0].message.content, CodeInferenceSchema)`
- Validate: one code per exemplar; if multiple, take first; if missing, skip with error log
- Return `List[CodeInference]`

---

**References:** ADR-010
