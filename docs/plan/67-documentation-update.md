---
title: "67 — documentation-update"
description: "Update all AGENTS.md with implementation notes; architecture diagrams; README"
updated_at: "2026-05-12"
phase: 11
---

# Feature 67: documentation-update


---

## Description

Update each `src/python/*/AGENTS.md` with implementation notes (what was built, known limitations, API reference). Add architecture diagrams in `docs/architecture/` (Mermaid or PNG). Update root `README.md` with quick-start guide: `mamba env create`, `pre-commit install`, `python -m analyze --data data/raw/data.csv --tags data/raw/tags.csv`. Ensure all AGENTS.md ≤100 lines.

---

## Acceptance Criteria

- Each AGENTS.md contains "Implementation Notes" section summarizing feature set delivered
- `docs/architecture/system-diagram.md` exists with DAG visualization
- `README.md` has correct command examples and troubleshooting section
- API reference generated via `pydoc-markdown` or similar (optional)
- Documentation builds with Quarto (if used): `quarto render docs/`

---

## Dependencies

@docs/plan/65-end-to-end-workflow-test.md

---

## Implementation Notes

- Update each layer's AGENTS.md with "Implementation Notes" subsection: list of features implemented, module locations, example usage
- Architecture diagram: use Mermaid in Markdown or PlantUML; render in README
- README: add Getting Started: 1. install mamba; 2. `mamba env create -f environment.yaml`; 3. `conda activate qda`; 4. `pre-commit install`; 5. `cp .env.example .env` and add `GROQ_API_KEY`; 6. `python -m analyze --data data/raw/data.csv --tags data/raw/tags.csv`
- Troubleshooting: common errors (missing API key, DuckDB locked, Groq rate limit)
- Keep AGENTS.md under 100 lines; move details to separate `IMPLEMENTATION.md` if needed

---

**References:** None
