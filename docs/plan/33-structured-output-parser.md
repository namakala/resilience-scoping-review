---
title: "33 — structured-output-parser"
description: "Strip fences, json.loads, validate Pydantic schemas (Code/Theme/Interpretation)"
updated_at: "2026-05-12"
phase: 5
---

# Feature 33: structured-output-parser


---

## Description

Parse LLM response text: strip markdown code fences (`````json` and ````'), call `json.loads()`, validate against Pydantic schemas: `CodeInference` (exemplar_id, code_name, definition, supporting_quote, related_existing_codes), `ThemeInference` (theme_name, narrative, code_ids), `InterpretationInference` (interpretation_name, narrative, theme_ids, key_insights). Raise `ParseError` on failure.

---

## Acceptance Criteria

- Fenced and unfenced JSON both accepted
- Trailing comma in JSON rejected with clear message
- Schema validation: required fields present, types correct (`code_name: str`, `exemplar_id: int`, etc.)
- Extra fields ignored with warning, not error
- Malformed JSON (syntax error) logs raw response for debugging and raises `ParseError`
- Parser unit-tested with sample valid/invalid responses

---

## Dependencies

@docs/plan/31-prompt-template-engine.md

---

## Implementation Notes

- Module: `src/python/inference/parsing.py`
- Strip: `text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.MULTILINE)`
- `data = json.loads(text)`
- Validate via Pydantic: `CodeInference(**item)` or `ThemeInference(**item)`
- `ParseError` custom exception with `response_text` attribute for debugging
- Logging: warn on extra fields `logger.warning("Extra fields in %s: %s", type, extra_keys)`

---

**References:** ADR-010
