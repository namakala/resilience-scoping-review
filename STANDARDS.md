---
title: "Coding Standards"
description: "Python and R coding standards for the project"
updated_at: "2026-05-12"
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

## Dependencies
Minimize external dependencies.
Declare dependencies explicitly.
Prefer standard library when available.
