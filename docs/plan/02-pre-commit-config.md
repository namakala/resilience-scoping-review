---
title: "02 — pre-commit-config"
description: "Pre-commit hooks: black, isort, mypy, flake8, pytest"
updated_at: "2026-05-12"
phase: 0
---

# Feature 02: pre-commit-config


---

## Description

Configure pre-commit hooks to enforce code quality: `black` (formatting), `isort` (import sorting), `mypy` (type checking), `flake8` (linting), and `pytest` (test runner). Hook configuration stored in `.pre-commit-config.yaml`.

---

## Acceptance Criteria

- `pre-commit install` runs successfully
- Staging a Python file automatically runs all hooks
- Hooks pass on correctly formatted/typed code
- Hook failures block commit with clear error messages
- Configuration includes `exclude: ^tests/fixtures/` to avoid formatting test data

---

## Dependencies

@docs/plan/00-environment-provisioning.md

---

## Implementation Notes

- `.pre-commit-config.yaml` with repos: `black`, `isort`, `mypy`, `flake8`, `pytest`
- Minimum version: pre-commit >= 3.0
- Hook order: black → isort → mypy → flake8 → pytest
- Configure `flake8` max-line-length=88 to match black

---

**References:** None
