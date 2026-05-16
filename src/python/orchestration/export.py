"""Export final ontology to JSON, CSV, and Markdown.

Queries the graph for all approved nodes, builds three representations
via ``export_formatters``, and writes them atomically via ``atomic_io``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
from config.config import Config
from orchestration.state import WorkflowState
from utils.atomic_io import write_csv, write_json, write_markdown
from utils.logging import get_logger

from .export_formatters import CSV_COLUMNS, _build_csv, _build_json, _build_markdown

logger = get_logger(__name__)

NODE_COLUMNS = "id, type, name, definition, tag, status, data_json"


def export_all(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    config: Config,
    db_path: Path | None = None,
) -> None:
    """Gather approved nodes, build all formats, write atomically."""
    output_dir = config.export_output_path
    output_dir.mkdir(parents=True, exist_ok=True)

    codes, themes, interpretations = _gather_approved_nodes(con, db_path)
    exemplar_map = _gather_exemplars(config)

    write_json(_build_json(codes, themes, interpretations), output_dir / "results.json")
    write_csv(
        _build_csv(interpretations, themes, codes, exemplar_map),
        CSV_COLUMNS,
        output_dir / "results.csv",
    )
    write_markdown(
        _build_markdown(interpretations, themes, codes, exemplar_map),
        output_dir / "results.md",
    )

    logger.info(
        "Export complete",
        extra={
            "codes": len(codes),
            "themes": len(themes),
            "interpretations": len(interpretations),
            "output_dir": str(output_dir),
        },
    )


# ── Data gathering ───────────────────────────────────────────────────


def _query_approved(
    con: duckdb.DuckDBPyConnection, node_type: str
) -> list[dict[str, Any]]:
    """Fetch all approved nodes of *node_type*, ordered by id."""
    rows = con.execute(
        f"SELECT {NODE_COLUMNS} FROM nodes "
        "WHERE type = ? AND status = 'approved' ORDER BY id",
        [node_type],
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        dj = None
        if row[6] is not None:
            try:
                dj = json.loads(row[6])
            except (json.JSONDecodeError, TypeError):
                dj = row[6]
        result.append(
            {
                "id": row[0],
                "type": row[1],
                "name": row[2] or "",
                "definition": row[3] or "",
                "tag": row[4],
                "status": row[5],
                "data_json": dj or {},
            }
        )
    return result


def _gather_approved_nodes(
    con: duckdb.DuckDBPyConnection, db_path: Path | None = None
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch all approved codes, themes, interpretations from the graph."""
    codes = _query_approved(con, "code")
    themes = _query_approved(con, "theme")
    interpretations = _query_approved(con, "interpretation")
    return codes, themes, interpretations


def _gather_exemplars(config: Config) -> dict[str, str]:
    """Load exemplar content from Parquet, keyed by exemplar id.

    Returns ``{exemplar_id_str: content}``. Falls back to empty dict
    when Parquet is unavailable.
    """
    try:
        from persistence.loaders import load_exemplars

        lf = load_exemplars()
        df = lf.select(["id", "content"]).collect()
        return {str(row["id"]): str(row["content"]) for row in df.iter_rows(named=True)}
    except Exception as exc:
        logger.warning("Could not load exemplars for export", extra={"error": str(exc)})
        return {}


__all__ = [
    "export_all",
    "_query_approved",
    "_gather_approved_nodes",
    "_gather_exemplars",
]
