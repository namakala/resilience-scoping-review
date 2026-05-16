"""Run subcommand — standalone click command registered via ``cli.add_command``.

Drives the full pipeline (stages 1-10) or selected types.  Replaces the
former ``generate`` subcommand.  Launches an interactive TUI when
running in a terminal.
"""

from __future__ import annotations

import sys

import click
from orchestration.config import (
    check_groq_key,
    common_options,
    resolve_data_path,
    resolve_tags_path,
    validate_paths,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# If we are in a TTY, launch the Textual TUI; otherwise fall back to CLI.
_INTERACTIVE_SESSION: bool = sys.stdout.isatty() and sys.stdin.isatty()


@click.command(
    "run",
    help="Run pipeline stages with HITL validation. "
    "Default (no flags) runs all stages. Use --type to run specific types.",
)
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(["code", "theme", "interpretation"]),
    help="Artifact type(s) to process (repeatable, e.g. --type code --type theme). "
    "Mutually exclusive with --all.",
)
@click.option(
    "--all",
    "all_flag",
    is_flag=True,
    default=False,
    help="Run all stages (default behavior). Mutually exclusive with --type.",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    show_default=True,
    help="Limit processing to N tags with exemplars (0=all). "
    "Tags with the most exemplars are selected first.",
)
@common_options
@click.pass_context
def run_cmd(
    ctx: click.Context,
    types: tuple[str, ...],
    all_flag: bool,
    limit: int,
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    quiet: bool,  # noqa: ARG001
) -> None:
    """Run pipeline stages with HITL validation between inference stages."""
    if types and all_flag:
        click.echo("Error: --type and --all are mutually exclusive.", err=True)
        sys.exit(1)

    if limit < 0:
        click.echo("Error: --limit must be a non-negative integer.", err=True)
        sys.exit(1)

    obj = ctx.obj
    data_path = resolve_data_path(obj)
    tags_path = resolve_tags_path(obj)

    if not validate_paths(data_path, tags_path):
        sys.exit(1)

    if not check_groq_key():
        sys.exit(1)

    if dry_run:
        click.echo("Dry-run: configuration valid. Ready to run.")
        if types:
            click.echo(f"  Types: {', '.join(types)}")
        else:
            click.echo("  All stages")
        click.echo(f"  Data: {data_path}")
        click.echo(f"  Tags: {tags_path}")
        if limit > 0:
            click.echo(f"  Limit: {limit} tag(s)")
        return

    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        run_sequence(con, types, ctx_obj=obj, limit=limit)
    finally:
        con.close()


# ── Public helpers (used by default.py) ─────────────────────────────────────


def run_sequence(
    con,
    types: tuple[str, ...],
    ctx_obj: dict | None = None,
    limit: int = 0,
) -> None:
    """Run pipeline from current state through target stage.

    Thin wrapper for programmatic use (default.py).  Resolves the
    initial state (fresh or resume via *ctx_obj* flags), creates
    config, and delegates to :func:`runner.run_pipeline`.

    When running in an interactive terminal, launches the Textual TUI
    instead of the sequential CLI pipeline.
    """
    from config.config import Config
    from orchestration.resume import handle_reset, resolve_state
    from orchestration.runner import resolve_target_stage

    env_file = ctx_obj.get("env_file") if ctx_obj else None

    if ctx_obj and ctx_obj.get("reset"):
        handle_reset(con)

    state = resolve_state(
        con,
        resume=bool(ctx_obj and ctx_obj.get("resume")),
        force_resume=bool(ctx_obj and ctx_obj.get("force_resume")),
        env_file=env_file,
    )
    config = Config.from_env()

    if _INTERACTIVE_SESSION and not types:
        _launch_tui(con, state, config)
        return

    from orchestration.runner import run_pipeline

    target = resolve_target_stage(types)
    final_state = run_pipeline(con, state, config, target_stage=target, limit=limit)
    logger.debug(
        "Pipeline complete",
        extra={"final_stage": final_state.current_stage},
    )


def _launch_tui(
    con,
    state,
    config,
) -> None:
    """Launch the Textual TUI for interactive pipeline execution."""
    try:
        from hitl.tui import AnalystTUI

        app = AnalystTUI(con, state, config)
        app.run()
    except ImportError as exc:
        logger.warning(
            "Textual not available; falling back to CLI pipeline",
            extra={"error": str(exc)},
        )
        from orchestration.runner import run_pipeline

        run_pipeline(con, state, config)


__all__ = ["run_cmd", "run_sequence"]
