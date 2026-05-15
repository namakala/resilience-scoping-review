"""Run subcommand — standalone click command registered via ``cli.add_command``.

Drives the full pipeline (stages 1-10) or selected types.  Replaces the
former ``generate`` subcommand.
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
@common_options
@click.pass_context
def run_cmd(
    ctx: click.Context,
    types: tuple[str, ...],
    all_flag: bool,
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    quiet: bool,  # noqa: ARG001
) -> None:
    """Run pipeline stages with HITL validation between inference stages."""
    if types and all_flag:
        click.echo("Error: --type and --all are mutually exclusive.", err=True)
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
        return

    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        run_sequence(con, types)
    finally:
        con.close()


# ── Public helpers (used by default.py) ─────────────────────────────────────


def run_sequence(con, types: tuple[str, ...]) -> None:
    """Run pipeline from current state through target stage.

    Thin wrapper for programmatic use (default.py).  Creates state + config,
    delegates to :func:`runner.run_pipeline`.
    """
    from orchestration.runner import resolve_target_stage, run_pipeline
    from orchestration.state import WorkflowState
    from persistence.state_repository import load_state
    from pipeline.config import Config

    state_dict = load_state(con)
    state = WorkflowState.from_state_dict(state_dict)
    config = Config.from_env()
    target = resolve_target_stage(types)

    final_state = run_pipeline(con, state, config, target_stage=target)
    logger.debug(
        "Pipeline complete",
        extra={"final_stage": final_state.current_stage},
    )


__all__ = ["run_cmd", "run_sequence"]
