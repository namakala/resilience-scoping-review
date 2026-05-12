---
title: "05 — csv-to-parquet-converter"
description: "Read data.csv and tags.csv; validate; write Parquet"
updated_at: "2026-05-12"
phase: 1
---

# Feature 05: csv-to-parquet-converter


---

## Description

Read `data/raw/data.csv` and `data/raw/tags.csv`. Validate schemas: `data.csv` must have columns `id, document, tag, content`; `tags.csv` must have `tag, description, n_contents`. Write validated data as Parquet to `data/processed/exemplars.parquet` and `data/processed/tags.parquet`.

---

## Acceptance Criteria

- Conversion preserves all rows and column types (id→int, document→str, tag→categorical, content→str)
- Missing values detected and rejected with clear error message
- Output Parquet files readable by Polars `scan_parquet` and pandas `read_parquet`
- File sizes smaller than original CSV by ≥50%
- Command-line script `scripts/convert_csv.py` can be run independently

---

## Dependencies

@docs/plan/01-project-scaffolding.md

---

## Implementation Notes

The converter was implemented with a modular architecture:

- **`reader.py`**: Read CSV with `pl.scan_csv`, schema validation, null/empty checks, enrichment (SHA256 content_hash, empty keywords), tag n_contents reconciliation from exemplars.
- **`writer.py`**: Write LazyFrame to Parquet with `sink_parquet`, compute row counts and compression ratio from actual file sizes. Shared between exemplars and tags.
- **`converter.py`**: Thin orchestrator class importing reader functions and writer. `CSVToParquetConverter.convert()` sequences: read exemplars → write exemplars → read tags → write tags. Convenience function `convert_csvs()` provides default-path entry point.
- **`exceptions.py`**: Custom exception hierarchy for clear error types.

The refactoring (executed after initial implementation) split the original 320-line monolithic `converter.py` into 4 focused modules (total ~265 lines, each ≤ 120 lines). All existing imports preserved; zero test changes required.

Schema enforcement: exemplars require `id, document, tag, content`; tags require `tag, description, n_contents`. Data quality rejects any null or whitespace-only values in `id` or `content`. Compression typically exceeds 50% reduction vs CSV.

## References

ADR-002 (Immutable Source of Truth), ADR-009 (Data Processing), STANDARDS.md (file length constraints).
