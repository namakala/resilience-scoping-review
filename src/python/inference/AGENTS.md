---
title: "Inference & LLM Layer"
description: "Groq batch inference: prompts, parsing, batching, retry, status tracking, and code inference service"
updated_at: "2026-05-16"
---

# Inference & LLM Layer

Batch LLM inference, prompt templating, structured output parsing, and incremental status tracking for code / theme / interpretation generation.

## Module Map

- `batching.py` — `group_by_tag(items, N)` → `list[Batch]`; `group_items_by_tag(items)` → `dict[str, list]`
- `code_inference.py` — `infer_codes(con, tag)` → `list[CodeInference]`
- `code_node_creation.py` — `create_code_nodes(con, codes)` → `list[int]`
- `exemplar_node_creation.py` — `ensure_exemplar_nodes(con, ids, tag)` → `dict[str, int]`
- `theme_code_loading.py` — `load_approved_codes(tag)`, `_load_exemplar_content_map(ids)`. Loads codes with exemplar content from Parquet.
- `theme_inference.py` — `infer_themes(con, tag)` → `list[ThemeInference]`
- `theme_node_reinfer.py` — `load_existing_draft_themes()`, `rename_node_raw()`
- `theme_name_utils.py` — `make_unique_theme_name()`, `check_duplicate_theme_names()`
- `theme_loading_for_interpretation.py` — `load_approved_themes(tag)`, loads themes with constituent code details and exemplar content.
- `interpretation_synthesis.py` — `synthesize_interpretations(con)` → `list[InterpretationInference]`
- `prompts.py` + `templates/` — Jinja2 rendering (code/theme/interpretation)
- `parsing.py` — fence stripping, JSON parse, Pydantic validation
- `retry.py` — network retry, rate-limit sleep, token-limit batch splitting
- `groq_client.py` — `complete(bundle)` → `ChatCompletion`
- `batch_processor.py` — `run_batches()` shared loop + `record_tokens()`
- `tag_context.py` — `get_tag_metadata(tag)` shared by all services
- `status_updates.py` — `mark_success()`, `mark_failure()` shared by all services
- `tracking.py` — `TokenTracker` singleton, cost estimation, log writer
- `fewshot_loader.py` — `load_fewshot(type)` from `fewshot/*.json`
- `inference_status_*.py` — DuckDB-backed lifecycle table (pending→generated→approved)

## Infrastructure

- **Retry:** Network errors → exponential backoff. 429 → 60s sleep. Token limit → split batch in half, retry recursively.
- **Batching:** `group_by_tag(items, max_per_batch)`. Items need `.tag` + `.id`. Deterministic by tag then id.
- **Token tracking:** `TokenTracker` records per-call usage, aggregates stage/session totals, writes JSON log, warns on cost threshold.

## Prompts

- `render_code_prompt`, `render_theme_prompt`, `render_interpretation_prompt`
- Each splits system (role + schema) and user (batch data). Few-shot pairs inserted between them.
- Config: `FEWSHOT_ENABLED` / `FEWSHOT_COUNT`, `CODE_TEMPERATURE` / `THEME_TEMPERATURE` / `INTERPRETATION_TEMPERATURE`

## Status

- `inference_status` table: `(entity_id, entity_type, stage) → pending → generated → approved → draft/rejected`
- `get_pending_items(stage, tag)` → entities needing inference. `set_status()` transitions states.

## Services

**`code_inference.py`:** Load pending exemplars → `group_by_tag(15)` → `run_batches(con, batches, _process_code_batch, STAGE_CODE)`. Per batch: fetch tag context + existing codes → load fewshot → `infer_batch_with_retry(render_fn, temperature=code_temperature())` → `parse_code_response` → dedup by exemplar_id → validate missing/extra IDs → `mark_success`/`mark_failure`. Returns `list[CodeInference]`.

**`interpretation_synthesis.py`:** Ready tags → `group_ready_tags_into_spans` → load approved themes per span → `run_batches(con, batches, _process_interpretation_span, STAGE_INTERPRETATION)`. Per span: build prompt context (tag hierarchy, ontology subtree, themes by tag) via `interpretation_span_grouping.py` pure functions → load fewshot → `infer_batch_with_retry(temperature=interpretation_temperature())` → `parse_interpretation_response` → `dedup_interpretation_names` + `flag_overlapping_themes` + `validate_theme_ids_exist` → `mark_success` per theme. Returns `list[InterpretationInference]`.

**Supporting modules:**
- `interpretation_span_grouping.py` — Pure DAG functions: `group_ready_tags_into_spans`, `build_tag_hierarchy`, `build_ontology_subtree`. No DB dependency.
- `theme_loading_for_interpretation.py` — `load_approved_themes(tag)`, `load_approved_themes_grouped(tags)`. Loads approved themes from graph.
- `interpretation_postprocess.py` — Pure validators: `dedup_interpretation_names`, `flag_overlapping_themes`, `validate_theme_ids_exist`.

## Design Notes

**Closure→partial:** `render_fn` was nested inside `infer_codes` loop, recreated every iteration. Extracted to module-level function; context passed via `functools.partial` making captures visible at call site.

**Shared orchestrator:** Batch loop + try/except repeated across services. Extracted to `batch_processor.run_batches()`. Each service provides a focused `_process_*_batch()` with only its specific logic.

**Public shared modules:** `tag_context` and `status_updates` extracted because all three services need them. Public modules (no underscore) with public functions — per CPython `urllib` cross-module convention.

**Config-driven temperature:** Hardcoded 0.3/0.4/0.5 → `*_TEMPERATURE` env vars following existing fewshot/config pattern.

## References

Implements ADR-010. See `@ADR.md` for rationale.
