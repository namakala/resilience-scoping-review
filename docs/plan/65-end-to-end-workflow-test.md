---
title: "65 — end-to-end-workflow-test"
description: "Seeded dataset runs all 10 stages; produces non-empty outputs; CI test"
updated_at: "2026-05-12"
phase: 11
---

# Feature 65: end-to-end-workflow-test


---

## Description

Create seeded dataset: 50 exemplars across 5 tags, pre-generated keywords, mock Groq responses (or live with small model). Run entire pipeline: load → embed → index → infer_codes → review_codes (auto-approve all) → infer_themes → review_themes (auto-approve) → infer_interpretations → review_interpretations (auto-approve) → export. Verify non-empty outputs at each stage.

---

## Acceptance Criteria

- Test runs in CI under `pytest -m "e2e"`; completes in <30min
- At least 1 code generated per exemplar
- At least 1 theme per tag with approved codes
- At least 1 interpretation spanning ≥2 tags
- Output files exist: `data/output/results.json`, `.csv`, `.md`
- No unhandled exceptions; exit code 0
- Test seeded with deterministic data (fixed random seed)

---

## Dependencies

@docs/plan/58-cli-entrypoint.md through @docs/plan/62-export-formatter.md

---

## Implementation Notes

- Module: `tests/integration/test_e2e.py`
- Fixtures in `tests/fixtures/seeded_data/`: `data.csv`, `tags.csv`, precomputed keywords.parquet
- Mock LLM: use `unittest.mock` to patch Groq client returning pre-canned JSON responses; or use tiny local model for speed
- Auto-approve: use `hitl` in non-interactive mode; `--auto-approve` flag or test harness
- Validate: after each stage, query database for counts: codes ≥50, themes ≥5, interpretations ≥1
- Use `subprocess.run(["python", "-m", "analyze", ...])` to test CLI entrypoint
- CI: GitHub Actions workflow `.github/workflows/e2e.yml` with `pytest -m "e2e"`

---

**References:** None
