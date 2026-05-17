"""Click group definition, subcommand registration, and entry point.

Subcommands are standalone click commands defined in sibling modules
(``ingest.py``, ``run.py``, ``review.py``) registered via
``cli.add_command()``.  ``ctx.obj`` is inherited from the group context.

The :func:`main` function wraps all execution in domain-specific error
handling with proper exit codes (0=success, 1=user interrupt,
2=config error, 3=storage corruption, 4=API failure).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import duckdb
from orchestration.config import load_configuration
from orchestration.default import handle_default
from orchestration.ingest import ingest_cmd
from orchestration.run import run_cmd
from persistence.duckdb_connection import get_connection
from utils.exceptions import ConfigurationError
from utils.logging import get_logger

from .errors import (
    EXIT_API_FAILURE,
    EXIT_CONFIG_ERROR,
    EXIT_STORAGE_CORRUPTION,
    EXIT_SUCCESS,
    EXIT_USER_INTERRUPT,
    check_integrity,
    handle_fatal_error,
    rebuild_database,
)

logger = get_logger(__name__)


@click.group(
    invoke_without_command=True,
    help="Ontology-guided thematic analysis with human-in-the-loop validation.",
)
@click.option(
    "--data",
    type=click.Path(dir_okay=False, resolve_path=True),
    help="Exemplars CSV path (overrides env/defaults)",
)
@click.option(
    "--tags",
    type=click.Path(dir_okay=False, resolve_path=True),
    help="Tags CSV path (overrides env/defaults)",
)
@click.option(
    "--env",
    "env_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="Custom .env file (overrides default .env values)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last session checkpoint",
)
@click.option(
    "--force-resume",
    is_flag=True,
    help="Override config version mismatch and resume anyway",
)
@click.option(
    "--reset",
    is_flag=True,
    help="Clear session state and restart from stage 1",
)
@click.pass_context
def cli(
    ctx: click.Context,
    data: Optional[str],
    tags: Optional[str],
    env_file: Optional[str],
    resume: bool,  # noqa: F811
    force_resume: bool,  # noqa: F811
    reset: bool,  # noqa: F811
) -> None:
    """Qualitative Thematic Analysis Pipeline.

    Ontology-guided thematic analysis with human-in-the-loop validation.
    Processes exemplars under hierarchical tags into codes, themes, and
    interpretations.
    """
    ctx.ensure_object(dict)
    ctx.obj["data"] = Path(data) if data else None
    ctx.obj["tags"] = Path(tags) if tags else None
    ctx.obj["env_file"] = Path(env_file) if env_file else None
    ctx.obj["resume"] = resume
    ctx.obj["force_resume"] = force_resume
    ctx.obj["reset"] = reset

    load_configuration(ctx.obj)

    if ctx.invoked_subcommand is None:
        handle_default(ctx.obj)


# ── Register standalone subcommands ─────────────────────────────────────────

cli.add_command(ingest_cmd)
cli.add_command(run_cmd)


# ── Public entry point ──────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the CLI.

    Wraps the Click group invocation in domain-specific error handling
    that maps failures to standardised exit codes.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0=success, 1=user interrupt, 2=config error,
        3=storage corruption, 4=API failure).
    """
    try:
        cli(args=argv, standalone_mode=True)
        return EXIT_SUCCESS
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USER_INTERRUPT
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return EXIT_USER_INTERRUPT
    except click.ClickException as exc:
        click.echo(f"Error: {exc.format_message()}", err=True)
        return EXIT_CONFIG_ERROR
    except duckdb.Error as exc:
        logger.error(
            "DuckDB error",
            extra={"error": str(exc), "error_type": "DuckDBError"},
        )
        if not _try_rebuild():
            logger.error("Database rebuild attempted but may be incomplete")
        return EXIT_STORAGE_CORRUPTION
    except ConfigurationError as exc:
        logger.error(
            "Configuration error",
            extra={"error": str(exc), "error_type": "ConfigurationError"},
        )
        return EXIT_CONFIG_ERROR
    except Exception as exc:
        return handle_fatal_error(exc, exit_code=EXIT_API_FAILURE)


# ── Private helpers ─────────────────────────────────────────────────────────


def _try_rebuild() -> bool:
    """Attempt to rebuild the database after corruption.

    Opens the default DuckDB database, runs ``PRAGMA integrity_check``,
    and if corruption is detected, drops all tables and recreates the
    schema from scratch.  Returns ``True`` if the rebuild was attempted
    (even if integrity already passed), ``False`` if the rebuild itself
    failed.

    The caller should **always** exit with ``EXIT_STORAGE_CORRUPTION``
    regardless of the return value — a rebuild means state was lost and
    the pipeline must restart from stage 1.
    """
    try:
        con = get_connection()
    except duckdb.Error as exc:
        logger.error(
            "Cannot open database for rebuild attempt",
            extra={"error": str(exc)},
        )
        return False

    try:
        ok = check_integrity(con=con)
        if ok:
            logger.info("Integrity check passed — no rebuild needed")
            return True

        logger.warning("Corruption detected — attempting schema rebuild")
        rebuild_database(con)
        return True
    except duckdb.Error as exc:
        logger.error(
            "Rebuild failed",
            extra={"error": str(exc)},
        )
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error during rebuild",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return False
    finally:
        try:
            con.close()
        except Exception:
            pass
