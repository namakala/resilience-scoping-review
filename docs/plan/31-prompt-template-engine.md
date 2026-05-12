---
title: "31 — prompt-template-engine"
description: "Jinja2 templates for code, theme, interpretation prompts"
updated_at: "2026-05-12"
phase: 5
---

# Feature 31: prompt-template-engine


---

## Description

Use Jinja2 to template three prompt types stored in `src/python/inference/templates/`:
- `code_inference.j2` — Provides: ontology path (ancestors), tag description, existing codes (name+definition), list of exemplars with `id, content, keywords`. Instructs: "Generate one code per exemplar as JSON array with fields: code_name, definition, supporting_quote, related_existing_codes."
- `theme_inference.j2` — Provides: tag context, list of codes (id, name, definition, exemplar_count). Instructs: "Group codes into themes; each theme includes theme_name, narrative, code_ids (2–5 codes per theme)."
- `interpretation_synthesis.j2` — Provides: multiple tags' themes, hierarchical context, ontology subtree diagram. Instructs: "Synthesize cross-cutting interpretations; each includes interpretation_name, narrative, theme_ids, key_insights."

All templates enforce JSON-only output with ````json` fence.

---

## Acceptance Criteria

- Templates render without errors given sample context dict
- Context variables: `ontology_path`, `tag_description`, `existing_codes`, `exemplars`, `themes`, `tag_hierarchy`
- Output format specified: "Respond ONLY with valid JSON array, no markdown, no extra text"
- Templates stored as `.j2` files in `src/python/inference/templates/`
- Unit test renders each template and checks for required placeholders

---

## Dependencies

@docs/plan/30-groq-client-initialization.md

---

## Implementation Notes

- Module: `src/python/inference/prompts.py`
- `from jinja2 import Environment, FileSystemLoader`
- Template dir: `os.path.join(os.path.dirname(__file__), 'templates')`
- Render: `env.get_template('code_inference.j2').render(**context)`
- Tests: load each template, render with minimal context, assert placeholders replaced (no `{{` remains)

---

**References:** ADR-010
