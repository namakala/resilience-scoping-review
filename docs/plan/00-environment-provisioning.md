---
title: "00 — environment-provisioning"
description: "Mamba/conda environment from environment.yaml with all dependencies"
updated_at: "2026-05-12"
phase: 0
---

# Feature 00: environment-provisioning


---

## Description

Create a fully reproducible conda/mamba environment from `environment.yaml`. Install all system and Python dependencies including Hamilton, DuckDB, sentence-transformers, Groq, and development tools.

---

## Acceptance Criteria

- `mamba env create -f environment.yaml` completes without errors
- `conda activate qda` succeeds
- `python -c "import hamilton, duckdb, sentence_transformers, groq, rich, questionary"` imports all modules without ImportError
- GROQ_API_KEY can be set in `.env` (template provided in `.env.example`)
- Environment includes both R (4.3.1) and Python (3.11) as specified

---

## Dependencies

None (foundational)

---

## Implementation Notes

- Environment name: `qda`
- Test import all packages in a clean shell
- Verify R version via `R --version`
- Create `.env.example` with `GROQ_API_KEY=your_key_here`

---

**References:** ADR-009 (Data Processing Framework)
