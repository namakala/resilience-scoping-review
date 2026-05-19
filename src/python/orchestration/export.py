"""Export final ontology to JSON, CSV, and Markdown.

Queries the graph for all approved nodes, builds three representations
via ``export_formatters``, and writes them atomically via ``atomic_io``.

Also provides the standalone ``export`` CLI subcommand with connection
and completion pre-checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import duckdb
from config.config import Config
from orchestration.state import WorkflowState
from persistence.duckdb_connection import DEFAULT_DB_PATH, get_connection
from persistence.state_repository import load_state
from utils.atomic_io import write_csv, write_json, write_markdown
from utils.logging import get_logger

from .errors import EXIT_STORAGE_CORRUPTION
from .export_formatters import CSV_COLUMNS, _build_csv, _build_json, _build_markdown

logger = get_logger(__name__)

NODE_COLUMNS = "id, type, name, definition, tag, status, data_json"


# ── Public API — called by runner stage 10 or standalone export ─────────


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

    _enrich_interp_theme_ids(con, interpretations)
    _enrich_theme_code_ids(con, themes)

    exemplar_map = _gather_exemplars(config)

    write_json(
        _build_json(codes, themes, interpretations, exemplar_map),
        output_dir / "results.json",
    )
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


# ── CLI subcommand ──────────────────────────────────────────────────────


@click.command(
    "export",
    help="Export approved codes, themes, and interpretations to "
    "JSON, CSV, and Markdown.",
)
@click.pass_context
def export_cmd(ctx: click.Context) -> None:
    """Standalone export entry point: ``python analyze.py export``.

    Pre-checks:
      1. DuckDB connection is reachable.
      2. Pipeline has produced approved interpretations (or stage >= 10).
    """
    con: duckdb.DuckDBPyConnection | None = None
    try:
        con = _check_connection()
        _check_completion(con)

        config = Config.from_env()
        state_dict = load_state(con)
        state = WorkflowState.from_state_dict(state_dict)

        click.echo(f"Exporting to {config.export_output_path}/")
        export_all(con, state, config)

        click.echo(
            f"Export complete: "
            f"{config.export_output_path / 'results.json'}, "
            f"{config.export_output_path / 'results.csv'}, "
            f"{config.export_output_path / 'results.md'}"
        )
    except SystemExit:
        raise
    except Exception as exc:
        logger.error(
            "Export failed", extra={"error": str(exc), "error_type": type(exc).__name__}
        )
        click.echo(f"Error: Export failed — {exc}", err=True)
        sys.exit(EXIT_STORAGE_CORRUPTION)
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


# ── Pre-checks ─────────────────────────────────────────────────────────


def _check_connection() -> duckdb.DuckDBPyConnection:
    """Verify DuckDB is reachable and has the expected schema.

    Returns an open connection.  Exits with ``EXIT_STORAGE_CORRUPTION``
    on failure.
    """
    try:
        con = get_connection()
    except duckdb.Error as exc:
        click.echo(
            f"Error: Cannot connect to session database ({DEFAULT_DB_PATH}). "
            f"Run 'python analyze.py run' first.\n  {exc}",
            err=True,
        )
        sys.exit(EXIT_STORAGE_CORRUPTION)

    try:
        con.execute("SELECT 1 FROM nodes LIMIT 1")
    except duckdb.Error:
        click.echo(
            "Error: Session database not initialized. "
            "Run 'python analyze.py run' first.",
            err=True,
        )
        sys.exit(EXIT_STORAGE_CORRUPTION)

    return con


def _check_completion(con: duckdb.DuckDBPyConnection) -> None:
    """Verify the pipeline has produced approved interpretations.

    Exits with a non-zero code if nothing to export.
    """
    try:
        state_dict = load_state(con)
        state = WorkflowState.from_state_dict(state_dict)
        if state.current_stage >= 10:
            return
    except Exception:
        pass

    count = con.execute(
        "SELECT COUNT(*) FROM nodes "
        "WHERE type = 'interpretation' AND status = 'approved'"
    ).fetchone()[0]

    if count == 0:
        click.echo(
            "Error: No approved interpretations found. "
            "Run the pipeline first with 'python analyze.py run'.",
            err=True,
        )
        sys.exit(1)

    click.echo(
        f"Warning: Pipeline export stage not yet complete, "
        f"but {count} approved interpretation(s) found.  Exporting anyway."
    )


# ── Data gathering ─────────────────────────────────────────────────────


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


def _gather_exemplars(config: Config) -> dict[str, dict[str, Any]]:
    """Load full exemplar data from Parquet, keyed by exemplar id string.

    Returns ``{exemplar_id_str: {id, document, tag, content, keywords}}``.
    Keywords are loaded from the separate ``keywords.parquet`` and merged
    by ``exemplar_id``.  Falls back to empty dict when Parquet is
    unavailable.
    """
    try:
        from persistence.loaders import load_exemplars, load_keywords

        lf = load_exemplars()
        df = lf.select(["id", "document", "tag", "content"]).collect()

        # Load keywords from keywords.parquet, group by exemplar_id
        kw_by_exemplar: dict[str, list[str]] = {}
        try:
            kw_lf = load_keywords()
            kw_df = kw_lf.select(["exemplar_id", "keyword_text"]).collect()
            for row in kw_df.iter_rows(named=True):
                eid = str(row["exemplar_id"])
                kw_by_exemplar.setdefault(eid, []).append(str(row["keyword_text"]))
        except Exception:
            pass

        result: dict[str, dict[str, Any]] = {}
        for row in df.iter_rows(named=True):
            str_id = str(row["id"])
            result[str_id] = {
                "id": row["id"],
                "document": str(row["document"]) if row["document"] is not None else "",
                "tag": str(row["tag"]) if row["tag"] is not None else "",
                "content": str(row["content"]) if row["content"] is not None else "",
                "keywords": kw_by_exemplar.get(str_id, []),
            }
        return result
    except Exception as exc:
        logger.warning("Could not load exemplars for export", extra={"error": str(exc)})
        return {}
    except Exception as exc:
        logger.warning("Could not load exemplars for export", extra={"error": str(exc)})
        return {}


# ── Edge-based enrichment ────────────────────────────────────────────────


def _enrich_interp_theme_ids(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[dict],
) -> None:
    """Populate ``data_json.theme_ids`` from ``spans`` edges when missing.

    The authoritative interpretation→theme relationship is stored in the
    ``edges`` table (``edge_type='spans'``).  Some interpretations may
    have empty or missing ``theme_ids`` in their ``data_json`` — this
    function fills them in so downstream formatters can traverse the
    hierarchy.
    """
    for interp in interpretations:
        dj = interp.get("data_json") or {}
        if dj.get("theme_ids"):
            continue
        rows = con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = ? AND edge_type = 'spans'",
            [interp["id"]],
        ).fetchall()
        tids = [r[0] for r in rows]
        if tids:
            interp["data_json"] = dj
            dj["theme_ids"] = tids


def _enrich_theme_code_ids(
    con: duckdb.DuckDBPyConnection,
    themes: list[dict],
) -> None:
    """Populate ``data_json.code_ids`` from ``composed-of`` edges when missing.

    Defensive enrichment for theme→code relationships.  Current pipeline
    already stores ``code_ids`` in theme ``data_json``, but if that ever
    changes this function ensures the export still works.
    """
    for theme in themes:
        dj = theme.get("data_json") or {}
        if dj.get("code_ids"):
            continue
        rows = con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = ? AND edge_type = 'composed-of'",
            [theme["id"]],
        ).fetchall()
        cids = [r[0] for r in rows]
        if cids:
            theme["data_json"] = dj
            dj["code_ids"] = cids


__all__ = [
    "export_all",
    "export_cmd",
    "_check_connection",
    "_check_completion",
    "_enrich_interp_theme_ids",
    "_enrich_theme_code_ids",
    "_query_approved",
    "_gather_approved_nodes",
    "_gather_exemplars",
]
