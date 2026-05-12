---
title: "69 — security-and-secrets"
description: "GROQ_API_KEY never committed; pre-commit secret scanning; .env .gitignore'd"
updated_at: "2026-05-12"
phase: 11
---

# Feature 69: security-and-secrets


---

## Description

Ensure GROQ_API_KEY and other secrets never committed. `.env` file in root, listed in `.gitignore`. Secret scanning pre-commit hook (e.g., `detect-secrets`). Document secret setup in README: "Copy `.env.example` to `.env` and add your key."

---

## Acceptance Criteria

- `.gitignore` contains `.env`, `data/output/*.duckdb` (maybe), `*.log`
- Pre-commit hook runs `detect-secrets` or `gitleaks`; blocks commit if secret pattern found
- No API keys in repository history (verified via `git log --patch | grep -i key`)
- README clearly states: "Never commit .env"
- Test: attempt to commit file containing `GROQ_API_KEY=abcd` → hook rejects

---

## Dependencies

@docs/plan/02-pre-commit-config.md
@docs/plan/58-cli-entrypoint.md

---

## Implementation Notes

- Add to `.pre-commit-config.yaml`:
  ```yaml
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
  ```
- Generate baseline: `detect-secrets scan > .secrets.baseline`
- `.gitignore`: add `.env`, `data/output/*.duckdb`, `data/output/*.log`, `*.egg-info/`, `__pycache__/`
- README section "Security": explain `.env` usage; never share keys
- Verify: `git log --all -p | grep -i "GROQ_API_KEY"` should return empty

---

**References:** None
