"""Generate subcommand — standalone click command registered via ``cli.add_command``.

Generates codes, themes, or interpretations via LLM inference with
HITL review between stages.
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


@click.command(
    "generate",
    help="Generate codes, themes, or interpretations via LLM inference. "
    "Each type is generated sequentially with HITL review between stages.",
)
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(["code", "theme", "interpretation"]),
    required=True,
    help="Artifact type(s) to generate (repeatable, e.g. --type code --type theme)",
)
@common_options
@click.pass_context
def generate_cmd(
    ctx: click.Context,
    types: tuple[str, ...],
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    quiet: bool,  # noqa: ARG001
) -> None:
    """Generate artifacts via LLM inference, with HITL after each type."""
    obj = ctx.obj
    data_path = resolve_data_path(obj)
    tags_path = resolve_tags_path(obj)

    if not validate_paths(data_path, tags_path):
        sys.exit(1)

    if not check_groq_key():
        sys.exit(1)

    if dry_run:
        click.echo("Dry-run: configuration valid. Ready to generate.")
        click.echo(f"  Types: {', '.join(types)}")
        click.echo(f"  Data: {data_path}")
        click.echo(f"  Tags: {tags_path}")
        return

    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        run_generate_sequence(con, types)
    finally:
        con.close()


# ── Public helpers (used by default.py) ─────────────────────────────────────


def run_generate_sequence(con, types: tuple[str, ...]) -> None:
    """Run generate + HITL for each type sequentially."""
    type_args = {
        "code": ("Infer Codes", 4),
        "theme": ("Infer Themes", 6),
        "interpretation": ("Infer Interpretations", 8),
    }

    for t in types:
        label, stage = type_args[t]
        click.echo(f"\n{'=' * 50}")
        click.echo(f"  Stage {stage}: {label}")
        click.echo(f"{'=' * 50}")

        pipeline_config = _build_pipeline_config()
        _run_inference(con, stage, pipeline_config)

        click.echo(f"\nEntering {t} review...")
        from orchestration.review import enter_review
        from persistence.duckdb_connection import DEFAULT_DB_PATH

        enter_review(con, t, DEFAULT_DB_PATH)


# ── Private helpers ─────────────────────────────────────────────────────────


def _build_pipeline_config():
    """Build a pipeline Config dataclass from merged env + CLI settings."""
    from pipeline.config import Config

    return Config.from_env()


def _run_inference(con, stage: int, pipeline_config) -> None:  # noqa: ARG001
    """Execute the pipeline DAG for *stage*."""
    from pipeline.constructor import create_pipeline
    from pipeline.executor import execute_dag

    builder = create_pipeline(pipeline_config)
    driver = builder.build()

    inputs: dict = {"dirty_flags": None}

    click.echo(f"  Running pipeline stage {stage}...")
    result = execute_dag(driver, stage=stage, inputs=inputs)

    if result.node_executions:
        executed = sum(1 for n in result.node_executions if n.status == "executed")
        cached = sum(1 for n in result.node_executions if n.status == "cached")
        click.echo(
            f"  Inference complete: " f"{executed} nodes executed, {cached} cache hits"
        )


__all__ = ["generate_cmd", "run_generate_sequence"]
