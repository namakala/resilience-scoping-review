---
title: "Human-in-the-Loop Validation Layer"
description: "CLI-based review and mutation workflows for qualitative validation"
updated_at: "2026-05-14"
---

# Human-in-the-Loop Validation Layer

Provides interactive command-line interface for researcher validation of codes, themes, and interpretations.

## Purpose

Researcher retains interpretive control. System proposes candidates; researcher approves, edits, merges, or rejects. All mutations recorded and undoable.

## Core Responsibilities

- Display pending codes, themes, interpretations in rich terminal UI
- Present supporting context: source exemplars, extracted keywords, semantic neighbors
- Capture user action via interactive prompts
- Validate requested actions against ontology constraints
- Persist mutations to graph database
- Manage undo/redo history for reversible actions
- Filter review items by status (draft, approved, rejected)

## Review Workflow

Three review modes operate independently:

**Code review:** Show code name, definition, supporting exemplar quote. List source exemplars (first few displayed, expandable). Show related codes by embedding similarity. Options: approve, edit definition, merge with another code, reject, defer, show more context.

**Theme review:** Show theme name and narrative. List constituent codes with exemplar counts. Display similar existing themes (if any). Options: approve, edit narrative (add/remove codes), merge, reject, defer.

**Interpretation review:** Show interpretation name and narrative. List themes included with tag context. Display affected ontology branches. Show evidence chain from interpretation down to exemplars. Options: approve, edit narrative (adjust scope), split into sub-interpretations, reject, defer.

## User Actions

Five atomic actions:

- **Approve** — Mark entity as approved, persist to graph
- **Edit** — Modify definition or narrative; resets status to draft; invalidates affected embeddings
- **Merge** — Combine two entities; redirect evidence; mark source as merged; invalidate caches
- **Reject** — Mark as rejected; do not propagate downstream
- **Defer** — Skip for later; keep in draft state

All actions written to user action log table. Timestamped for audit trail.

## Rich Terminal UI

Uses `rich` library for formatted panels, tables, and syntax highlighting. Uses `questionary` for interactive prompts with arrow-key selection. Displays hierarchical context clearly using indented text panels.

## Undo/Redo

Action history stack stores chronological user actions. Undo reverses last action; redo reapplies undone action. History depth unlimited but bounded by session. Undo/redo respect constraint validation — illegal reversions rejected with error.

## State Mutations

Mutations update graph immediately (no staging area). Status transitions trigger downstream effects:

- Code approval may enable theme inference for its tag
- Theme approval may enable interpretation synthesis for its tag span
- Edits to definition or narrative invalidate embedding cache for that entity

Invalidation cascades marked via dirty flags. Next pipeline run recomputes affected branches.

## Constraints (ADR-011)

Review actions must not violate ADR-013 constraints:

- Cannot approve theme with codes from multiple tags
- Cannot merge code and theme (type mismatch)
- Cannot approve interpretation with non-contiguous tag span

Check rejected if constraints violated. Error message includes remediation suggestion.

## Integration

- Calls `@src/python/graph/AGENTS.md` to persist mutations
- Calls `@src/python/ontology/AGENTS.md` for constraint checks
- Notifies `@src/python/pipeline/AGENTS.md` of dirty flags for recomputation
- Retrieves neighbors from `@src/python/semantic/AGENTS.md` for context
- Loads artifacts from `@src/python/persistence/AGENTS.md`

## Testing

Unit tests for action validation, merge logic, undo/redo consistency. Integration tests for full review cycles: code→approve→theme→approve→interpretation. Mock prompts allow automated testing of interactive flows.

## References

Implements ADR-011 (Human-in-the-Loop Validation). See `@ADR.md` for validation philosophy and trade-offs.
