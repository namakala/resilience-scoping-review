---
title: "58 — cli-entrypoint"
description: "argparse/click entrypoint; parse --data, --tags, --stage, --resume, --config"
updated_at: "2026-05-12"
phase: 10
---

# Feature 58: cli-entrypoint


---

## Description

`python -m analyze [--data data.csv] [--tags tags.csv] [--stage N] [--resume] [--config config.yaml]`. Parse arguments with `argparse` or `click`. Validate paths exist, stage integer in 1–10, config file well-formed (YAML). Load environment variables from `.env` if present.

---

## Acceptance Criteria

- `--help` displays all options with descriptions
- Missing required args (data, tags) prints error and exits with code 1
- Config file overrides defaults: `embedding_model`, `batch_size`, `groq_model`, `log_level`
- Paths resolved to absolute; existence checked before start
- Dry-run mode (`--dry-run`) validates setup without executing pipeline

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

- Module: `src/python/orchestration/cli.py` or `analyze.py` at root
- Entry point in `pyproject.toml` or `setup.py`: `console_scripts = ['analyze = analyze:main']`
- Required args: `--data PATH`, `--tags PATH`
- Optional: `--stage N` (start at stage N); `--resume` (load state); `--config YAML`
- Load `.env`: `from dotenv import load_dotenv; load_dotenv()`
- Validate: `Path(data).exists()`, `1 <= stage <= 10`
- Config: `yaml.safe_load(open(config))`; merge with defaults

---

**References:** None
