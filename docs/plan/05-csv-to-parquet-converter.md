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

- Use Polars `scan_csv` for lazy read, then `sink_parquet`
- Schema validation: check required columns, no nulls in `id`, `content`
- Log row counts before/after; report compression ratio
- Script entry point: `if __name__ == "__main__": main()`

---

**References:** ADR-002 (Immutable Source of Truth), ADR-009 (Data Processing)
