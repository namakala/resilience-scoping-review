---
title: "62 — export-formatter"
description: "Serialize final ontology to JSON, CSV, Markdown"
updated_at: "2026-05-15"
phase: 10
---

# Feature 62: export-formatter


---

## Description

After stage 10 (export), serialize final ontology to multiple formats in `data/output/`:
- `results.json`: hierarchical JSON with keys `codes` (by tag), `themes` (by tag), `interpretations` (with nested themes/codes)
- `results.csv`: flattened table with columns: `interpretation, theme, code, exemplar_id, exemplar_content, tag_path`
- `results.md`: human-readable Markdown report with headings per interpretation, subheadings per theme, bulleted codes with exemplar quotes

---

## Acceptance Criteria

- JSON matches schema: each code has `id, name, definition, tag, exemplar_ids`; each theme has `id, name, narrative, tag, code_ids`; each interpretation has `id, name, narrative, theme_ids, tag_spans`
- CSV includes all leaf-level evidence (each code→exemplar pair as row)
- Markdown report readable in 80-column terminal; includes table of contents
- All files written atomically (temp file then rename)
- Export idempotent: re-export produces identical files (deterministic ordering)

---

## Dependencies

@docs/plan/51-interpretation-approval-finalizes.md

---

## Implementation Notes

- Module: `src/python/orchestration/export.py`
- Gather all approved nodes: `codes = get_nodes_by_type_and_tag('code', status='approved')`, similarly themes and interpretations
- Build JSON: nested dict: `{codes_by_tag: {tag: [code_dict]}, themes_by_tag: {tag: [theme_dict]}, interpretations: [interp_dict]}`
- `interp_dict['themes']` = list of theme dicts (each includes codes recursively)
- CSV flatten: for each interpretation → each theme → each code → each exemplar (via `contains` edges) → row with full chain
- Markdown: `# Interpretations`, for each: `## {name}`, `### Themes`, `#### {theme_name}`, bullet list codes with supporting quote
- Atomic write: write to temp file `results.json.tmp` then `os.rename`

---

**References:** None
