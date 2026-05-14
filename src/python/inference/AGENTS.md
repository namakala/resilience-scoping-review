---
title: "Inference & LLM Layer"
description: "Manages Groq batch inference, prompt templates, structured output parsing, tag-based batching, and retry logic"
updated_at: "2026-05-14"
---

# Inference & LLM Layer

Handles all LLM interactions. Prepares batches, constructs prompts, calls Groq API, parses structured JSON outputs.

## Purpose

Generate semantic artifacts (codes, themes, interpretations) from exemplars and keywords via LLM reasoning. Ensure outputs are constrained, consistent, and structurally valid.

## Core Responsibilities

- Batch exemplars and codes for efficient API utilization
- Template prompts with ontology context and existing artifacts
- Call Groq API with retry logic and rate-limit handling
- Parse and validate structured JSON responses using Pydantic schemas
- Track token consumption and cost per stage
- Support incremental inference (only new or modified items)

## Retry Logic (Feature 35)

Three-tier retry for Groq API calls via `src/python/inference/retry.py`:

- **Network errors** (timeout, connection): exponential backoff via tenacity (2s, 4s, 8s, max 3 attempts).
- **Rate limit** (HTTP 429): sleep 60s, retry once.
- **Token limit** (context-length error): raises `TokenLimitError`; `infer_batch_with_retry()` splits the batch via `split_batch_in_half()` and retries each half.
- All retries logged per batch_id for audit.
- Low-level: `call_complete_with_retry()` wraps a single `complete()` call.
- High-level: `infer_batch_with_retry()` takes a `Batch` + render function, handles all modes.

## Batching Strategy (ADR-010)

Group exemplars by parent tag into fixed-size batches using
`src/python/inference/batching.py`.

`group_by_tag(items, max_per_batch=15, prefix="tag")` takes any iterable
of `BatchableItem` objects (must expose `.tag: str` and `.id: int | str`),
groups by `.tag`, sorts by `.id`, splits into chunks of `max_per_batch`,
and returns `list[Batch]`.

The `Batch` dataclass carries: `tag`, `items`, `batch_index`,
`total_batches`, `item_count` (computed), and a `batch_id` property
(format: `{prefix}_{tag}_batch_{index:02d}`).

Usage: code inference batches exemplars, theme inference batches
approved codes, interpretation batches themes by tag-span combination.
Items with an empty/falsy tag are silently skipped. Tags with more than
max_per_batch items split into multiple batches; the last batch may be
smaller.

Larger batches reduce API calls but risk coherence loss. Smaller
batches improve quality at higher cost. Batches submitted sequentially.

## Few-Shot Examples

Curated examples loaded from ``src/python/inference/fewshot/*.json``
via ``load_fewshot()`` in ``fewshot_loader.py``. Each JSON file
contains ``{"user": ..., "assistant": ...}`` pairs mirroring the
rendered prompt format. Examples span two domains (resilience scoping
review and universal healthcare coverage). Default: 2 examples per
call. Configurable via ``FEWSHOT_ENABLED``, ``FEWSHOT_COUNT``,
``FEWSHOT_SHUFFLE`` env vars.

Examples injected as alternating ``user``/``assistant`` message pairs
by ``build_messages()``, between ``system`` and the actual ``user``
message. No changes to Jinja2 templates needed.

Future enhancement: replace static JSON pool with dynamic retrieval
from previously approved inference results once critical mass (>50
pairs) is available.

## Prompt Engineering

Three prompt types, all demanding structured JSON output:

**Code inference prompt:** Provides context (ontology path, tag description, existing codes) and lists exemplars with keywords. Instructs LLM to generate one code per exemplar, with name, definition, supporting quote, and related existing codes. Emphasizes distinctiveness and ground truth.

**Theme inference prompt:** Provides codes for a single tag. Asks LLM to group related codes into themes. Each theme includes name, narrative, and list of code_ids. Enforces 2–5 codes per theme for coherence.

**Interpretation synthesis prompt:** Provides themes from multiple tags, hierarchical context, and ontology subtree structure. Asks LLM to synthesize cross-cutting interpretations with narrative and key insights.

Prompts avoid over-specification. LLM acts as constrained interpreter, not ontology designer.

## API Integration

Groq client uses OpenAI GPT OSS 120B. API key loaded from environment (GROQ_API_KEY). Client configured with timeout and retry middleware.

Error handling:

- Network errors: exponential backoff, up to 3 retries
- Rate limit errors: 60-second pause, then retry
- Token limit exceeded: split batch via `split_batch_in_half()`, retry each half via `infer_batch_with_retry()`
- Invalid JSON: log error, return empty list, flag for manual retry

## Output Parsing

Raw LLM response text stripped of markdown fences. Parsed with `json.loads`. Each item validated against Pydantic schema:

- `CodeInference`: exemplar_id, code_name, definition, supporting_quote, related_existing_codes
- `ThemeInference`: theme_name, narrative, code_ids
- `InterpretationInference`: interpretation_name, narrative, theme_ids, key_insights

Validation failures raise errors. HITL layer may later edit parsed outputs.

## Token Tracking

Each response logs input and output token counts. Cumulated per session. Cost estimation uses Groq pricing (input $0.15/1M tokens, output ~$0.6/1M tokens). Typical stage costs: code inference (50–200K tokens), theme inference (30–100K), interpretation (10–30K).

## Constraints

LLM never modifies ontology structure. All tag assignments validated against loaded ontology. No open-ended text responses accepted — only JSON matching schema.

## References

Implements ADR-010 (LLM Inference Strategy). See `@ADR.md` for detailed constraints and rationale.
