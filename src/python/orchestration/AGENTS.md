---
title: "Orchestration Layer — CLI & Config"
description: "Click-based CLI, subcommands (ingest, run, review), env var merging, ingest guardrail"
updated_at: "2026-05-16"
---

# Orchestration Layer

Click-based CLI for the thematic analysis pipeline. Three subcommands plus a smart default.

## CLI Structure

```
analyze [global-opts] <command> [sub-opts]

Global options:
  --data PATH         Exemplars CSV path (overrides env/defaults)
  --tags PATH         Tags CSV path (overrides env/defaults)
  --env FILE          Custom .env file (overrides default .env values)
  --resume            Resume from last checkpoint
  --force-resume      Override config version mismatch and resume anyway
  --reset             Clear session state and restart from stage 1
  --dry-run           Validate all config, don't execute
  --verbose           Show detailed progress output
  --quiet             Suppress non-error output

Commands:
  ingest              Ingest CSV data into DuckDB session
  run [--all|--type]  Run pipeline stages with HITL validation
  export              Export approved codes, themes, interpretations
  review              Enter HITL review TUI
  (no command)        Default: review with empty-check prompt
```

## Subcommands

**ingest:**
- Converts CSV to Parquet, initializes DuckDB schema, stores content hashes
- Guardrail: SHA-256 content hashing prevents accidental re-ingest of unchanged data
- Re-ingest blocked with "No changes detected" message unless files have changed
- `--force` skips confirmation prompt when re-ingesting changed data

**run:**
- Default (no flags) runs all stages from stage 1 through export
- `--resume` restores from last checkpoint; logs `"Resuming from stage N (checkpoint T)"`
- `--force-resume` overrides config version mismatch when resuming
- `--reset` clears session state before starting
- `--type code|theme|interpretation` limits to specific artifact types (repeatable)
- `--all` explicitly requests all stages (mutually exclusive with --type)
- `--limit N` restricts analysis stages (code, theme, interpretation) to N tags with the most exemplars (n_contents > 0). Default 0 = all tags.
- Drives stages via ``runner.run_pipeline()`` with checkpoint after each stage
- Runs HITL review automatically after inference stages (5, 7, 9)

**export:**
- Exports approved codes, themes, and interpretations to JSON, CSV, and Markdown
- Pre-checks: DuckDB connection + pipeline completion (stage >= 10 or approved interpretations exist)
- Writes to ``EXPORT_OUTPUT_PATH`` (default ``data/output``) as ``results.json``, ``results.csv``, ``results.md``
- Standalone command: ``python analyze.py export``; also invoked as pipeline stage 10

**review:**
- Enters HITL review TUI using rich panels and questionary prompts
- Default (no --type): reviews all pending artifacts
- `--type code` limits review to codes only

**Default (no subcommand):**
- Queries DuckDB for existing artifacts
- If nothing to review, prompts to run code generation first
- Otherwise enters review TUI

## Config Loading

1. Load default `.env` from CWD
2. If `--env FILE` given, load with `override=True`
3. CLI flags set `DATA_PATH` / `TAGS_PATH` in os.environ
4. `config/settings.py` reads from os.environ lazily
5. Precedence: CLI → --env → .env → defaults

## Ingest Guardrail

Hash utilities in `hash_utils.py` compute SHA-256 of CSV file contents.
Hashes stored in DuckDB session state as `data_content_hash` and
`tags_content_hash`. On re-ingest, hashes are compared. Only if different
does re-ingest proceed.

## Modules

- `cli.py` — Click group, subcommand definitions, dispatch, progress display
- `run.py` — ``run`` subcommand: ``run_cmd()`` CLI handler, ``run_sequence()`` programmatic entry
- `runner.py` — Sequential stage-transition driver: ``run_pipeline()`` dispatches service modules per stage, ``resolve_target_stage()``
- `export.py` — Orchestrate final export: query approved graph nodes, delegate to formatters + atomic I/O; also provides ``export_cmd`` Click subcommand with connection and completion pre-checks
- `export_formatters.py` — Pure JSON/CSV/Markdown format builders (no I/O, no DB); builds array-based JSON, per-exemplar CSV, and labelled-heading Markdown
- `hash_utils.py` — File hashing: `compute_file_hash()`, `check_ingest_allowed()`, `record_ingest_hashes()`
- `state.py` — `WorkflowState` dataclass: stage transitions, serialization, dirty flags, config hash
- `state_rules.py` — Stage constants (`MIN_STAGE`, `MAX_STAGE`, `STAGE_PREREQS`) + field validation
- `resume.py` — Session resume logic: `resolve_state()` (fresh vs resume branching, config version validation), `handle_reset()` (clear session state)

## Integration

- Calls `persistence.converter.convert_csvs()` and `persistence.duckdb_init.init_or_migrate()`
- Calls `hitl.code_review.review_codes()`, `hitl.theme_review.review_themes()`, etc.
- Calls service modules directly via ``runner.run_pipeline()`` sequential dispatch
- Calls `orchestration.export.export_all()` after stage 10 to write results; ``orchestration.export.export_cmd`` registered as standalone Click subcommand
- Reads config from `config.settings`
- Stores state via `persistence.state_repository` (checkpoint after each stage)

## References

docs/plan/58-cli-entrypoint.md
docs/plan/64-session-resume-logic.md
