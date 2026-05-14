---
title: "Inference Layer"
description: "Groq batch LLM inference, structured JSON generation, retry logic, and incremental status tracking for codes, themes, and interpretations"
updated_at: 2026-05-14
---

# Inference Layer

Manages all LLM interactions: batch preparation, prompt templating, Groq API calls, structured JSON parsing, and inference lifecycle tracking.

## Purpose & Design Rationale (ADR-010)

Generate semantic artifacts — codes from exemplars, themes from codes, interpretations from themes — via constrained LLM reasoning. ADR-010 mandates Groq for cost-effective batch inference, with three guardrails: (1) outputs must be valid JSON matching Pydantic schemas; (2) batch grouping by parent tag keeps inferences semantically coherent; (3) LLM never mutates ontology structure, only assigns content to existing tags.

**Constrained interpreter design:** The LLM acts as an analyst, not a designer. Prompts provide ontology context (tag description, ancestor path, existing codes) and exemplar evidence, then instruct the model to generate grounded, distinct outputs. This prevents ontology drift and ensures traceable lineage from raw data to interpretation.

**Incremental inference tracking:** An `inference_status` table records lifecycle states (pending → generated → approved → draft). HITL edits mark entities "draft" to flag them for re-inference. The pipeline calls `get_pending_items()` before each stage to avoid wasteful recomputation. Dirty-state propagation (ADR-007) ensures only affected ontology branches are re-batched and re-submitted.

**Three-tier retry strategy:** Infrastructure failures are inevitable. Network errors (timeout, connection) retry with exponential backoff (2s, 4s, 8s, max 3 attempts). Rate limits (HTTP 429) pause 60 seconds then retry once. Token-limit errors (context-length exceeded) raise `TokenLimitError`; the caller splits the batch in half and recursively retries each half via `infer_batch_with_retry()`. All retries are logged per batch_id for audit.

**Few-shot demonstrations:** Curated JSON examples (one per prompt type) are loaded from `fewshot/*.json` and injected as alternating `user`/`assistant` message pairs. Configurable count (default 2) and optional shuffle. This steers the LLM toward the expected output format and granularity without fine-tuning. Future enhancement: dynamically retrieve examples from previously approved results once >50 pairs exist.

## Core Components

**Prompt Engineering** (`prompts.py`, `templates/`): Three prompt bundles — `render_code_prompt` (exemplars → codes, one per exemplar), `render_theme_prompt` (approved codes → grouped themes, 2–5 codes each), `render_interpretation_prompt` (themes across tags → cross-cutting interpretations). Each bundle splits system (role, rules, output schema) and user (batch data) content. Few-shot pairs are inserted between system and user messages.

**Batch Grouping** (`batching.py`): `group_by_tag(items, max_per_batch=15)` takes any `BatchableItem` (objects with `.tag` and `.id`), groups by `.tag`, sorts by `.id`, and chunks into `Batch` objects. Batches are deterministic and sequentially submitted. The `Batch` dataclass carries `tag`, `items`, `batch_index`, `total_batches`, `item_count`, and a `batch_id` property (`{prefix}_{tag}_batch_{NN}`). `split_batch_in_half(batch)` recursively handles token-limit errors.

**Retry & Error Handling** (`retry.py`): Two entry points. `call_complete_with_retry()` wraps a single Groq call with network + rate-limit retry. `infer_batch_with_retry(batch, render_fn)` calls the render function, retries with splitting on `TokenLimitError`, and returns a list of ChatCompletion objects (one or multiple if split).

**Groq Client** (`groq_client.py`): Singletons `get_sync_client()` and `get_client()` (async). `complete(bundle)` builds messages via `build_messages(system, user, fewshot)`, sets `response_format={"type": "json_object"}` and `temperature=0`. Client configured with timeout and max_retries from `config.py` (Groq API key from `GROQ_API_KEY`).

**Output Parsing** (`parsing.py`): Raw responses stripped of markdown fences, parsed with `json.loads`, unwrapped from top-level keys (`"codes"`, `"themes"`, `"interpretations"`), and validated against Pydantic models (`CodeInference`, `ThemeInference`, `InterpretationInference`). Extra fields are logged as warnings; validation failures raise `ParseError`.

**Token Tracking** (`tracking.py`): `TokenTracker` logs per-call usage (input/output tokens, cost) to `data/output/token_usage.log` and aggregates per-stage and session totals. Cost estimates use Groq pricing (input $0.15/M, output $0.60/M). Warnings emitted if stage cost exceeds `MAX_STAGE_COST_USD` threshold. `recent_usage(window_seconds=60)` supports rate-limit awareness.

**Few-Shot Loader** (`fewshot_loader.py`): `load_fewshot(prompt_type, count=2, shuffle=False)` reads `src/python/inference/fewshot/{prompt_type}.json` and returns up to `count` examples. Files contain `{"user": "...", "assistant": "..."}` pairs mirroring the rendered prompt structure. Missing files return empty list (graceful degradation).

**Inference Status** (`inference_status_crud.py`, `inference_status_queries.py`): DuckDB-backed status tracker. `set_status()` transitions an entity to a new state (pending/generated/approved/rejected). `set_status_draft()` marks an entity for rework (increments `attempts`). `batch_set_status()` bulk upserts. Query-side `get_pending_items(stage, tag=None)` returns IDs needing processing. Table created idempotently via `init_inference_status_table()`.

## File Organization

- `prompts.py` — Jinja2 loader, `PromptBundle`, render functions (code/theme/interpretation)
- `batching.py` — `BatchableItem` protocol, `Batch` dataclass, `group_by_tag()`, `split_batch_in_half()`
- `retry.py` — `TokenLimitError`, `call_complete_with_retry()`, `infer_batch_with_retry()`
- `groq_client.py` — singleton clients, `build_messages()`, `complete()`
- `parsing.py` — Pydantic schemas, `parse_*_response()` functions, JSON fence stripping
- `tracking.py` — `TokenTracker`, cost computation, stage/session summaries, log writer
- `fewshot_loader.py` — `load_fewshot()` for curated examples
- `inference_status_crud.py` — upsert operations (set_status, set_status_draft, batch_set_status)
- `inference_status_queries.py` — get_pending_items, get_stage_summary, get_status
- `inference_status_types.py` — status constants (PENDING, GENERATED, APPROVED, DRAFT, REJECTED), DDL
- `tracking_types.py` — `UsageRecord` dataclass
- `tracking_decorator.py` — optional decorator for auto-tracking
- `templates/` — six Jinja2 templates (3 system + 3 user)

## Integration

Called by pipeline stages:
- Stage 4 (Infer Codes) batches exemplars per tag
- Stage 6 (Infer Themes) batches approved codes per tag
- Stage 8 (Infer Interpretations) batches approved themes by cross-tag span

Provides parsed artifacts to HITL review stages (5, 7, 9). TokenTracker feeds cost monitoring dashboards. Inference status enables dirty-state propagation: when an entity is edited (draft), downstream stages know to exclude it from re-inference until re-approved.

The layer depends on:
- **Ontology layer** — tag paths, descriptions, constraint context
- **Semantic layer** — neighbor/retrieval results for few-shot enrichment (future)
- **Persistence layer** — embedding cache for token estimation (optional)

## Constraints

- No open-ended text: every LLM call requests JSON matching a fixed schema.
- Temperature 0 for deterministic outputs.
- Batch size capped at 15 by default (quality vs cost trade-off).
- Token limits trigger automatic batch splitting, not hard failures.
- All prompts include ontology context to ground responses in the existing tag hierarchy.

## References

Implements ADR-010 (LLM Inference Strategy) and ADR-007 (Incremental Evolution). See `@ADR.md` for architecture-wide rationale. Complements Semantic Retrieval (`@docs/feature/semantic-retrieval.md`) and Ontology (`@docs/feature/ontology-feature.md`) layers.
