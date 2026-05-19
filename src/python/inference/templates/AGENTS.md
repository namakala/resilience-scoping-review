---
title: "Prompt Template Layer"
description: "Jinja2 templates for LLM prompts with system/user role separation"
updated_at: "2026-05-16"
---

# Prompt Template Layer

Six Jinja2 templates compose LLM prompts for code inference, theme
inference, and interpretation synthesis. Each prompt type splits into
a system template (role + schema + rules) and a user template (batch
data). Decouples prompt text from inference logic.

## Message Role Architecture

Groq supports only `system`, `user`, `assistant`, `tool`, `function`
roles. No `example_user` or `developer`. The inference layer builds:

1. **system** — role persona, behavior rules, output schema, stopping
   conditions. Rendered from `*_system.j2`. Shared across batch calls.
2. **user** (repeated) — batch-specific data: ontology context,
   exemplars, keywords, existing codes. Rendered from `*_user.j2`.
3. **assistant** (optional) — few-shot demonstration responses,
   alternating with user messages to show the expected output pattern.

Few-shot uses standard multi-turn format: `user` → `assistant` pairs
in the messages array. No special roles needed. Curated examples live
in ``src/python/inference/fewshot/*.json`` and are loaded by
``load_fewshot()`` at call time (see ``fewshot_loader.py``).

Use `response_format={"type": "json_object"}` on every inference call
(Groq API parameter). Templates still describe the expected JSON shape
since JSON mode guarantees valid JSON, not correct schema.

## Context Engineering Principles

**Outcome-first prompts** (OpenAI GPT-5.5): Define the destination,
not every step. Describe success, constraints, evidence. Avoid
process-heavy instruction stacks.

**Context as finite resource** (Anthropic): Every token consumes
attention budget. Keep each section to the smallest set of high-signal
tokens. Organize with Markdown headers. Start minimal; add detail only
where failure modes surface.

**Structure and clarity** (OpenAI best practices): Instructions at the
top. Use `##` headers to distinguish instruction from context. Frame
positively: say what to do instead of what not to do.

**Output constraints** (all three): Demand JSON matching the Pydantic
schema. Show expected shape inline. Temperature 0 for all extraction.

## Template Catalog

**code_inference_system.j2** — Role, instructions, output schema.
**code_inference_user.j2** — Ontology path, tag description, existing
codes, exemplars with keywords.

**theme_inference_system.j2** — Role, grouping rules, output schema.
**theme_inference_user.j2** — Tag context, code list with definitions,
exemplar counts, and full supporting exemplar content.

**interpretation_synthesis_system.j2** — Role, synthesis rules,
stopping rule (synthesize from provided themes, do not re-derive),
output schema.
**interpretation_synthesis_user.j2** — Hierarchical context, ontology
subtree, themes grouped by tag with constituent code details and
supporting exemplar content.

## Style and Conventions

- System template: first line is `You are a {role} performing {task}.`
- User template: starts with `## {Section}` header (no role preamble).
- System template always ends with the output schema and `Respond with
  a valid JSON array wrapped in ```json ... ```.`
- No fluff: avoid "fairly", "quite", "just", "simply".
- Positive framing: "Respond with" not "Do not include".
- Leading word: open the expected JSON fence in the template.
- Few-shot examples: loaded from JSON via ``load_fewshot()``; use
  alternating `user`/`assistant` message pairs. See ``fewshot_loader.py``
  and ``fewshot/*.json``.

## References

- OpenAI Prompt Guidance (GPT-5.5) — outcome-first, stopping rules
- Anthropic Context Engineering — context-as-resource, section headers
- OpenAI Best Practices — structure, specificity, positive framing
- ADR-010 (LLM Inference Strategy) — batch grouping, prompt types
- Groq Python SDK — supported roles, response_format
