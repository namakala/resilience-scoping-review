---
title: "58 — cli-entrypoint"
description: "Click-based CLI with subcommands (ingest, generate, review), --env config, ingest guardrail, smart default"
updated_at: "2026-05-15"
phase: 10
---

# Feature 58: cli-entrypoint

---

## Description

`python -m analyze [--data data.csv] [--tags tags.csv] [--env custom.env] [--resume] <command> [sub-opts]`. Click-based CLI replacing the old argparse stub. Three subcommands: `ingest`, `generate`, `review`. When no subcommand is given, defaults to review with a prompt to generate if no artifacts exist. Config loading uses `.env` + optional `--env` override.

---

## Acceptance Criteria

- `--help` displays global options (--data, --tags, --env, --resume) and all subcommands
- Missing required args on subcommands prints error and exits with code 1
- `--env FILE` loads custom env vars with override=True; precedence: CLI > --env > .env > defaults
- Paths resolved to absolute; existence checked per-subcommand before execution
- Dry-run mode (`--dry-run`) validates setup without executing pipeline (on each subcommand)
- Ingest guardrail: SHA-256 content hashing prevents accidental re-ingest of unchanged data; prints "Request Denied: No changes detected on ingested data"
- Generate accepts repeatable `--type` (code, theme, interpretation); HITL review runs after each type
- Review enters HITL TUI via rich/questionary; --type filters to code/theme/interpretation
- No subcommand: queries DuckDB for existing codes; if none found, prompts "Generate codes first? [y/N]"

---

## Dependencies

@docs/plan/01-project-scaffolding.md
click>=8.1.0

---

## Implementation Notes

- Module: `analyze.py` at root (thin entry point with sys.path setup) and `src/python/orchestration/cli.py` (click group + subcommands)
- Entry point in `pyproject.toml`: `[project.scripts] analyze = analyze:main`
- Subcommand structure: `ingest`, `generate`, `review` under a `@click.group(invoke_without_command=True)`
- Global options: `--data PATH`, `--tags PATH`, `--env FILE`, `--resume`
- Subcommand options: `--dry-run`, `--verbose`, `--quiet` on each subcommand via `_common_options` decorator
- `ingest`: CSV→Parquet via `convert_csvs()`, DuckDB init via `init_or_migrate()`, content hashing via `hash_utils.py`
- `generate`: run inference DAG per type, then enter HITL review; progress display inline
- `review`: call hitl.code_review/hitl.theme_review/hitl.interpretation_review
- Ingest guardrail: `hash_utils.compute_file_hash()` → SHA-256; stored in DuckDB session state
- Config: `load_dotenv()` + `load_dotenv(env_file, override=True)` → modifies os.environ → `Config.from_env()`

---

## Implementation Completion

**Completed:** 2026-05-15

All acceptance criteria satisfied:

- Created `src/python/orchestration/` package with `__init__.py` and `AGENTS.md`
- Created `src/python/orchestration/cli.py`: click group with 3 subcommands + smart default
- Created `src/python/orchestration/hash_utils.py`: SHA-256 content hashing for ingest guardrail
- Refactored `analyze.py` to thin entry point delegating to `orchestration.cli.main()`
- Added `click>=8.1.0` dependency and `[project.scripts]` entry to `pyproject.toml`
- 29 unit tests passing (19 CLI tests + 10 hash_utils tests)

**Git:** Not committed (user discretion).

**References:** None
