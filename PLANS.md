# Development Plan Checklist

Simple checklist. Each item is a link to a detailed feature file. When a feature is done, mark `[x]`. Optionally add commit hash after the link.

## Phase 0 — Foundation (00–04)

- [x] @docs/plan/00-environment-provisioning.md (verified: env works, imports OK, R 4.3.1)
- [x] @docs/plan/01-project-scaffolding.md (dirs: tests/{unit,integration,fixtures}, data/output; 7x src/python/*/__init__.py; analyze.py stub; .gitignore updated)
- [x] @docs/plan/02-pre-commit-config.md (hooks: black/isort/mypy/flake8/pytest; fixtures excluded; pytest as local hook)
- [x] @docs/plan/03-logging-framework.md (implemented: JSON logging, rotation, sensitive filter; commit 1fa4384)
- [x] @docs/plan/04-error-handling-utilities.md (implemented: @make_retry with exponential backoff, @make_circuit_breaker with half-open recovery, graceful_shutdown context manager; commit [will be added])

## Phase 1 — Persistence Layer (05–10)

- [x] @docs/plan/05-csv-to-parquet-converter.md (implemented: CSVToParquetConverter class, schema validation, n_contents reconciliation, nullable keywords/content_hash enrichment; 8 tests pass)
- [ ] @docs/plan/06-artifact-loaders.md
- [ ] @docs/plan/07-duckdb-schema-init.md
- [ ] @docs/plan/08-embedding-cache-schema.md
- [ ] @docs/plan/09-bm25-index-serialization.md
- [ ] @docs/plan/10-session-state-manager.md

## Phase 2 — Graph Module (11–16)

- [ ] @docs/plan/11-networkx-graph-construction.md
- [ ] @docs/plan/12-node-insertion-api.md
- [ ] @docs/plan/13-edge-creation-api.md
- [ ] @docs/plan/14-node-query-operations.md
- [ ] @docs/plan/15-basic-traversal.md
- [ ] @docs/plan/16-graph-transactional-updates.md

## Phase 3 — Ontology Layer (17–22)

- [ ] @docs/plan/17-tag-dag-construction.md
- [ ] @docs/plan/18-ontology-traversal-ops.md
- [ ] @docs/plan/19-traversal-cache-materialization.md
- [ ] @docs/plan/20-incremental-cache-invalidation.md
- [ ] @docs/plan/21-constraint-validator.md
- [ ] @docs/plan/22-scope-restriction-helper.md

## Phase 4 — Semantic Layer (23–29)

- [ ] @docs/plan/23-sentence-transformer-initialization.md
- [ ] @docs/plan/24-exemplar-embedding-generation.md
- [ ] @docs/plan/25-keyword-embedding-generation.md
- [ ] @docs/plan/26-bm25-index-builder.md
- [ ] @docs/plan/27-embedding-similarity-computation.md
- [ ] @docs/plan/28-hybrid-retrieval-engine.md
- [ ] @docs/plan/29-neighbor-discovery-service.md

## Phase 5 — Inference Layer (30–36)

- [ ] @docs/plan/30-groq-client-initialization.md
- [ ] @docs/plan/31-prompt-template-engine.md
- [ ] @docs/plan/32-batch-grouping-by-tag.md
- [ ] @docs/plan/33-structured-output-parser.md
- [ ] @docs/plan/34-token-tracking-middleware.md
- [ ] @docs/plan/35-retry-and-rate-limit-handling.md
- [ ] @docs/plan/36-incremental-inference-tracker.md

## Phase 6 — Code Inference & Review (37–41)

- [ ] @docs/plan/37-code-inference-service.md
- [ ] @docs/plan/38-code-node-creation.md
- [ ] @docs/plan/39-code-hitl-cli.md
- [ ] @docs/plan/40-code-merge-action.md
- [ ] @docs/plan/41-code-edit-embeddings-invalidation.md

## Phase 7 — Theme Inference & Review (42–46)

- [ ] @docs/plan/42-theme-inference-service.md
- [ ] @docs/plan/43-theme-node-creation.md
- [ ] @docs/plan/44-theme-hitl-cli.md
- [ ] @docs/plan/45-theme-constraint-validation.md
- [ ] @docs/plan/46-theme-approval-enables-interpretation.md

## Phase 8 — Interpretation Synthesis & Review (47–51)

- [ ] @docs/plan/47-interpretation-synthesis-service.md
- [ ] @docs/plan/48-interpretation-node-creation.md
- [ ] @docs/plan/49-interpretation-hitl-cli.md
- [ ] @docs/plan/50-multi-tag-span-validation.md
- [ ] @docs/plan/51-interpretation-approval-finalizes.md

## Phase 9 — Pipeline Orchestration (52–57)

- [ ] @docs/plan/52-dag-constructor.md
- [ ] @docs/plan/53-node-function-definitions.md
- [ ] @docs/plan/54-dependency-wiring.md
- [ ] @docs/plan/55-dirty-flag-propagation.md
- [ ] @docs/plan/56-selective-execution.md
- [ ] @docs/plan/57-cache-miss-handling.md

## Phase 10 — Orchestration Layer (58–64)

- [ ] @docs/plan/58-cli-entrypoint.md
- [ ] @docs/plan/59-state-machine-implementation.md
- [ ] @docs/plan/60-stage-transition-driver.md
- [ ] @docs/plan/61-hitl-coordination.md
- [ ] @docs/plan/62-export-formatter.md
- [ ] @docs/plan/63-error-recovery-handler.md
- [ ] @docs/plan/64-session-resume-logic.md

## Phase 11 — Integration & System Completion (65–70)

- [ ] @docs/plan/65-end-to-end-workflow-test.md
- [ ] @docs/plan/66-performance-benchmarks.md
- [ ] @docs/plan/67-documentation-update.md
- [ ] @docs/plan/68-logs-and-observability.md
- [ ] @docs/plan/69-security-and-secrets.md
- [ ] @docs/plan/70-final-validation-checklist.md

---

## How to Use

- Each link points directly to a feature specification file.
- Mark `[x]` when implemented. Optionally append commit hash: `[x] @docs/plan/...  abc123`
- If a feature is revised, update the linked file's `updated_at` frontmatter.

---

## Legend

- `[ ]` — Not started
- `[x]` — Implemented and tested
- `[~]` — In progress (optional)

**Total features:** 71
