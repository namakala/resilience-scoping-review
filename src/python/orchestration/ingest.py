"""Ingest subcommand — standalone click command registered via ``cli.add_command``.

Converts CSV to Parquet, initialises DuckDB schema, and stores content
hashes for change detection on subsequent runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import click
from orchestration.config import (
    check_groq_key,
    common_options,
    resolve_data_path,
    resolve_tags_path,
    validate_paths,
)


@click.command(
    "ingest",
    help="Ingest CSV data into DuckDB session. "
    "Converts CSV to Parquet, initializes DuckDB schema, "
    "and stores content hashes for change detection.",
)
@click.option(
    "--data",
    type=click.Path(dir_okay=False, resolve_path=True),
    help="Exemplars CSV path (overrides global --data)",
)
@click.option(
    "--tags",
    type=click.Path(dir_okay=False, resolve_path=True),
    help="Tags CSV path (overrides global --tags)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation prompt when re-ingesting changed data",
)
@common_options
@click.pass_context
def ingest_cmd(
    ctx: click.Context,
    data: Optional[str],
    tags: Optional[str],
    force: bool,  # noqa: ARG001
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    quiet: bool,  # noqa: ARG001
) -> None:
    """Ingest CSV data into DuckDB session."""
    obj = ctx.obj

    data_path = resolve_data_path(obj, Path(data) if data else None)
    tags_path = resolve_tags_path(obj, Path(tags) if tags else None)

    os.environ["DATA_PATH"] = str(data_path)
    os.environ["TAGS_PATH"] = str(tags_path)

    if not validate_paths(data_path, tags_path):
        sys.exit(1)

    if not check_groq_key():
        sys.exit(1)

    if dry_run:
        click.echo("Dry-run: configuration valid. Ready to ingest.")
        click.echo(f"  Data: {data_path}")
        click.echo(f"  Tags: {tags_path}")
        return

    from orchestration.hash_utils import check_ingest_allowed, record_ingest_hashes
    from persistence.converter import convert_csvs
    from persistence.duckdb_connection import DEFAULT_DB_PATH
    from persistence.duckdb_init import init_or_migrate

    click.echo("Initializing DuckDB session...")
    con = init_or_migrate()
    try:
        if not check_ingest_allowed(con, data_path, tags_path):
            sys.exit(0)

        click.echo("Converting CSV to Parquet...")
        convert_csvs(exemplars_csv=data_path, tags_csv=tags_path)

        click.echo("Recording ingest hashes...")
        record_ingest_hashes(con, data_path, tags_path)

        click.echo(f"Ingest complete. Session database: {DEFAULT_DB_PATH}")
    finally:
        con.close()
