---
title: "Orchestration Layer — CLI & Config"
description: "Click-based CLI, subcommands (ingest, generate, review), env var merging, ingest guardrail"
updated_at: "2026-05-15"
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
  --dry-run           Validate all config, don't execute
  --verbose           Show detailed progress output
  --quiet             Suppress non-error output

Commands:
  ingest              Ingest CSV data into DuckDB session
  generate            Generate codes, themes, or interpretations
  review              Enter HITL review TUI
  (no command)        Default: review with empty-check prompt
```

## Subcommands

**ingest:**
- Converts CSV to Parquet, initializes DuckDB schema, stores content hashes
- Guardrail: SHA-256 content hashing prevents accidental re-ingest of unchanged data
- Re-ingest blocked with "No changes detected" message unless files have changed
- `--force` skips confirmation prompt when re-ingesting changed data

**generate:**
- Accepts repeatable `--type` (code, theme, interpretation)
- Runs inference sequentially: generate → HITL → next type
- Shows batch progress: `[Batch N/M] Tag '...' — sending to LLM...`
- Each type's HITL session must complete before advancing

**review:**
- Enters HITL review TUI using rich panels and questionary prompts
- Default (no --type): reviews all pending artifacts
- `--type code` limits review to codes only

**Default (no subcommand):**
- Queries DuckDB for existing artifacts
- If nothing to review, prompts to generate codes first
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
- `hash_utils.py` — File hashing: `compute_file_hash()`, `check_ingest_allowed()`, `record_ingest_hashes()`

## Integration

- Calls `persistence.converter.convert_csvs()` and `persistence.duckdb_init.init_or_migrate()`
- Calls `hitl.code_review.review_codes()`, `hitl.theme_review.review_themes()`, etc.
- Calls `pipeline.executor.execute_dag()` for inference
- Reads config from `config.settings`
- Stores state via `persistence.state_repository`

## References

docs/plan/58-cli-entrypoint.md
