"""Click group definition, subcommand registration, and entry point.

Subcommands are standalone click commands defined in sibling modules
(``ingest.py``, ``generate.py``, ``review.py``) registered via
``cli.add_command()``.  ``ctx.obj`` is inherited from the group context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from orchestration.config import load_configuration
from orchestration.default import handle_default
from orchestration.generate import generate_cmd
from orchestration.ingest import ingest_cmd
from orchestration.review import review_cmd


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
@click.pass_context
def cli(
    ctx: click.Context,
    data: Optional[str],
    tags: Optional[str],
    env_file: Optional[str],
    resume: bool,  # noqa: F811
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

    load_configuration(ctx.obj)

    if ctx.invoked_subcommand is None:
        handle_default(ctx.obj)


# ── Register standalone subcommands ─────────────────────────────────────────

cli.add_command(ingest_cmd)
cli.add_command(generate_cmd)
cli.add_command(review_cmd)


# ── Public entry point ──────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the CLI.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (``0`` for success, ``1`` for error).
    """
    try:
        cli(argv=argv, standalone_mode=True)
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except click.ClickException as exc:
        click.echo(f"Error: {exc.format_message()}", err=True)
        return 1
    except Exception as exc:
        click.echo(f"Unexpected error: {exc}", err=True)
        return 1
