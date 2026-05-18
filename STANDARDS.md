---
title: "Coding Standards"
description: "Python and R coding standards for the project"
updated_at: "2026-05-17"
---

# Coding Standards

Generic rules for Python and R code.

## File Organization
Keep related functions together.
One module per cohesive responsibility.
Use clear directory structure mirroring feature areas.

## File Length
Maximum file length: 300 lines.
If file exceeds 200 lines, consider refactoring.
Split large files into multiple focused modules.

## Naming
Python: snake_case for functions/variables, PascalCase for classes.
R: snake_case for variables, lowerPascalCase for functions.
Names must be descriptive and unambiguous.

## Line Length
Maximum line length: 79 characters.
Wrap long expressions clearly.
Use parentheses for implicit line continuation.

## Documentation
Python: docstrings for all public functions/classes.
R: roxygen comments for all exported functions.
Document purpose, parameters, returns, and examples.

## Functions
Keep functions small and focused.
One function does one thing.
Avoid deep nesting (max 3 levels).

## Error Handling
Handle errors explicitly.
Log errors with context.
Fail fast with clear messages.

## Testing
Write tests for all new code.
Place tests mirroring source structure.
Keep tests small and independent.

## Mocking
Mock external dependencies at their interface boundary.
Use spec-validated mocks that fail when the real API changes.
Python: prefer autospec=True on @mock.patch.
R: validate mock signatures match the mocked function's formal arguments.

## Dependencies
Minimize external dependencies.
Declare dependencies explicitly.
Prefer standard library when available.

## Documentation Voice

Follow `@docs/methods/_overview.qmd` as the canonical reference.

Declarative SVO sentences. Open with the subject being described.
Simple past for implementation; simple present for system behavior;
shall for requirements. No future tense or conditionals.

One concept per paragraph. Topic sentence first.
Bullet lists for enumerations. Never inline-enumerate in prose.

No hedging, questions, exclamations, or second person.
No editorializing adverbs ("importantly", "notably").
No "in order to" — use bare infinitive.

@path for files. ADR-NNN for decisions. [@citation] for references.

NOTE: Agentic documentation (AGENTS.md, STANDARDS.md, PLANS.md,
plan breakdowns) uses directive fragments, no subjects.
The rules above apply to formal documentation:
methods, results, overviews.
