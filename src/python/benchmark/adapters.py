"""Load and align MC and human-coder benchmark data.

MC data is loaded from DuckDB + Parquet by leveraging ``orchestration.export``
internals (``_gather_approved_nodes``, ``_gather_exemplars``, ``_build_csv``).
Human-coder data is loaded from CSV files with the same schema.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
from config.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

REQUIRED_HC_COLUMNS = frozenset(["id", "document", "tag", "content", "code", "theme"])


def load_mc_dataframe(
    con: duckdb.DuckDBPyConnection, config: Config
) -> list[dict[str, str]]:
    """Build the MC results dataframe by reusing export infrastructure.

    Queries approved nodes from the DuckDB graph, loads exemplars and
    keywords from Parquet, and builds the standard per-exemplar CSV
    schema (id, document, tag, content, keywords, code, theme, interpretation).

    Returns an empty list if no approved nodes are found.
    """
    from orchestration.export import _gather_approved_nodes, _gather_exemplars
    from orchestration.export_formatters import _build_csv

    codes, themes, interpretations = _gather_approved_nodes(con)
    if not interpretations:
        logger.warning("No approved interpretations found in DuckDB")
        return []

    # Enrich theme → code and interpretation → theme edges
    _enrich_interp_theme_ids(con, interpretations)
    _enrich_theme_code_ids(con, themes)

    exemplar_map = _gather_exemplars(config)
    rows = _build_csv(interpretations, themes, codes, exemplar_map)
    logger.info(
        "MC dataframe built",
        extra={
            "codes": len(codes),
            "themes": len(themes),
            "interpretations": len(interpretations),
            "rows": len(rows),
        },
    )
    return rows


def load_hc_dataframe(path: Path) -> list[dict[str, str]]:
    """Load a human-coder CSV into a list of dicts.

    Validates that required columns are present.  Lowercases column names
    for case-insensitive matching.  Returns an empty list if the file is
    empty or unreadable.

    Raises:
        ValueError: If required columns are missing.
    """
    path = Path(path)
    if not path.exists():
        logger.warning("HC file not found", extra={"path": str(path)})
        return []

    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []

        # Normalise column names to lowercase
        lower_cols = {c.strip().lower(): c.strip() for c in reader.fieldnames}
        missing = REQUIRED_HC_COLUMNS - set(lower_cols.keys())
        if missing:
            raise ValueError(
                f"HC file {path} missing required columns: {missing}. "
                f"Found: {sorted(lower_cols.keys())}"
            )

        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append(
                {
                    "id": str(row[lower_cols["id"]]).strip(),
                    "document": str(row[lower_cols["document"]]).strip(),
                    "tag": str(row[lower_cols["tag"]]).strip(),
                    "content": str(row[lower_cols["content"]]).strip(),
                    "keywords": str(
                        row.get(lower_cols.get("keywords", ""), "")
                    ).strip(),
                    "code": str(row[lower_cols["code"]]).strip(),
                    "theme": str(row[lower_cols["theme"]]).strip(),
                }
            )

    logger.info("HC dataframe loaded", extra={"path": str(path), "rows": len(rows)})
    return rows


def align_dataframes(
    mc_rows: list[dict[str, str]],
    hc_rows: list[dict[str, str]],
    label: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Align MC and HC dataframes to the intersection of exemplar IDs.

    Returns (mc_aligned, hc_aligned) tuples where both lists are in the
    same order (sorted by exemplar ID) and contain only IDs present in
    both frames.

    The *label* is used for logging (e.g. ``"HC1"``).
    """
    mc_by_id = {r["id"]: r for r in mc_rows}
    hc_by_id = {r["id"]: r for r in hc_rows}
    common = sorted(mc_by_id.keys() & hc_by_id.keys())
    logger.info(
        "Aligned %s: %d common exemplars out of MC=%d, HC=%d",
        label,
        len(common),
        len(mc_by_id),
        len(hc_by_id),
    )
    return [mc_by_id[eid] for eid in common], [hc_by_id[eid] for eid in common]


def _fetch_edge_targets(
    con: duckdb.DuckDBPyConnection, source_id: int, edge_type: str
) -> list[int]:
    """Fetch target IDs from edges table for a given source and edge type."""
    rows = con.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = ?",
        [source_id, edge_type],
    ).fetchall()
    return [r[0] for r in rows]


def _enrich_interp_theme_ids(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[dict],
) -> None:
    """Populate ``data_json.theme_ids`` from ``spans`` edges when missing."""
    for interp in interpretations:
        dj = interp.get("data_json") or {}
        if dj.get("theme_ids"):
            continue
        tids = _fetch_edge_targets(con, interp["id"], "spans")
        if tids:
            interp["data_json"] = dj
            dj["theme_ids"] = tids


def _enrich_theme_code_ids(
    con: duckdb.DuckDBPyConnection,
    themes: list[dict],
) -> None:
    """Populate ``data_json.code_ids`` from ``composed-of`` edges when missing."""
    for theme in themes:
        dj = theme.get("data_json") or {}
        if dj.get("code_ids"):
            continue
        cids = _fetch_edge_targets(con, theme["id"], "composed-of")
        if cids:
            theme["data_json"] = dj
            dj["code_ids"] = cids
