---
title: "Inference & LLM Layer"
description: "Manages Groq batch inference, prompt templates, and structured output parsing"
updated_at: "2026-05-11"
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

## Batching Strategy (ADR-010)

Group exemplars by parent tag to maintain contextual coherence. Each batch contains:

- Tag name and hierarchical path (ancestors up to root)
- Tag description from ontology
- Existing codes in that tag (for consistency)
- Grouped exemplars (default 15 per batch)
- Extracted keyword lists

Larger batches reduce API calls but risk coherence loss. Smaller batches improve quality at higher cost. Batches submitted sequentially.

## Prompt Engineering

Three prompt types, all demanding structured JSON output:

**Code inference prompt:** Provides context (ontology path, tag description, existing codes) and lists exemplars with keywords. Instructs LLM to generate one code per exemplar, with name, definition, supporting quote, and related existing codes. Emphasizes distinctiveness and ground truth.

**Theme inference prompt:** Provides codes for a single tag. Asks LLM to group related codes into themes. Each theme includes name, narrative, and list of code_ids. Enforces 2–5 codes per theme for coherence.

**Interpretation synthesis prompt:** Provides themes from multiple tags, hierarchical context, and ontology subtree structure. Asks LLM to synthesize cross-cutting interpretations with narrative and key insights.

Prompts avoid over-specification. LLM acts as constrained interpreter, not ontology designer.

## API Integration

Groq client uses Mixtral model (or GPT OSS equivalent if available). API key loaded from environment (GROQ_API_KEY). Client configured with timeout and retry middleware.

Error handling:

- Network errors: exponential backoff, up to 3 retries
- Rate limit errors: 60-second pause, then retry
- Token limit exceeded: split batch, retry halves
- Invalid JSON: log error, return empty list, flag for manual retry

## Output Parsing

Raw LLM response text stripped of markdown fences. Parsed with `json.loads`. Each item validated against Pydantic schema:

- `CodeInference`: exemplar_id, code_name, definition, supporting_quote, related_existing_codes
- `ThemeInference`: theme_name, narrative, code_ids
- `InterpretationInference`: interpretation_name, narrative, theme_ids, key_insights

Validation failures raise errors. HITL layer may later edit parsed outputs.

## Token Tracking

Each response logs input and output token counts. Cumulated per session. Cost estimation uses Groq pricing (input ~$0.0001/1K tokens, output ~$0.0003/1K tokens). Typical stage costs: code inference (50–200K tokens), theme inference (30–100K), interpretation (10–30K).

## Constraints

LLM never modifies ontology structure. All tag assignments validated against loaded ontology. No open-ended text responses accepted — only JSON matching schema.

## References

Implements ADR-010 (LLM Inference Strategy). See `@ADR.md` for detailed constraints and rationale.
