---
title: "01 — project-scaffolding"
description: "Directory structure: src/python/, tests/, docs/plan/, data/{raw,processed,output}"
updated_at: "2026-05-12"
phase: 0
---

# Feature 01: project-scaffolding


---

## Description

Create the complete directory structure required by the architecture: `src/python/{persistence,graph,ontology,semantic,inference,hitl,pipeline}`; `tests/{unit,integration,fixtures}`; `docs/plan/`; and `data/{raw,processed,output}`. Each Python package gets an `__init__.py`.

---

## Acceptance Criteria

- All directories exist with correct permissions
- Each `src/python/*/__init__.py` is empty or contains package docstring
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` exist
- `data/raw/`, `data/processed/`, `data/output/` directories exist
- Root-level `analyze.py` or `src/python/__main__.py` placeholder present

---

## Dependencies

@docs/plan/00-environment-provisioning.md

---

## Implementation Notes

- Use `mkdir -p` to create nested directories
- Touch empty `__init__.py` files
- Create placeholder `analyze.py` with `print("Not implemented")` or pass
- Ensure `.gitignore` covers `data/output/`, `.env`, `__pycache__/`

---

**References:** None
