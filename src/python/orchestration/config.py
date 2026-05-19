"""Shared configuration helpers for CLI subcommands.

Provides the ``common_options`` decorator, ``.env`` loading, path
resolution, and validation helpers shared across all subcommands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import click
from dotenv import load_dotenv

# ── Shared click option decorator ────────────────────────────────────────────


def common_options(f: object) -> object:
    """Decorate a subcommand with ``--dry-run``, ``--verbose``, ``--quiet``.

    These must be on each subcommand (click does not inherit group
    options), placed *after* the subcommand name in invocation.
    """
    f = click.option(
        "--dry-run", is_flag=True, help="Validate config without executing"
    )(f)
    f = click.option("--verbose", is_flag=True, help="Show detailed progress output")(f)
    f = click.option("--quiet", is_flag=True, help="Suppress non-error output")(f)
    return f


# ── Configuration loading ───────────────────────────────────────────────────


def load_configuration(obj: dict) -> None:
    """Load ``.env``, optional ``--env`` file, and CLI overrides into ``os.environ``."""
    load_dotenv(override=False)

    env_file = obj.get("env_file")
    if env_file:
        load_dotenv(dotenv_path=env_file, override=True)

    data_path = obj.get("data")
    if data_path:
        os.environ["DATA_PATH"] = str(data_path)

    tags_path = obj.get("tags")
    if tags_path:
        os.environ["TAGS_PATH"] = str(tags_path)


# ── Path helpers ─────────────────────────────────────────────────────────────


def resolve_data_path(obj: dict, cli_arg: Path | None = None) -> Path:
    """Resolve data path: CLI arg > group arg > env var > default."""
    if cli_arg:
        return cli_arg
    if obj.get("data"):
        return cast(Path, obj["data"])
    return Path(os.getenv("DATA_PATH", "data/raw/data.csv"))


def resolve_tags_path(obj: dict, cli_arg: Path | None = None) -> Path:
    """Resolve tags path: CLI arg > group arg > env var > default."""
    if cli_arg:
        return cli_arg
    if obj.get("tags"):
        return cast(Path, obj["tags"])
    return Path(os.getenv("TAGS_PATH", "data/raw/tags.csv"))


def validate_paths(data_path: Path, tags_path: Path) -> bool:
    """Check both paths exist. Print errors and return ``False`` if not."""
    ok = True
    if not data_path.exists():
        click.echo(f"Error: Data file not found: {data_path}", err=True)
        ok = False
    if not tags_path.exists():
        click.echo(f"Error: Tags file not found: {tags_path}", err=True)
        ok = False
    return ok


def check_groq_key() -> bool:
    """Check ``GROQ_API_KEY`` is set. Print error and return ``False`` if not."""
    if not os.getenv("GROQ_API_KEY"):
        click.echo(
            "Error: GROQ_API_KEY is not set. " "Add it to your .env file or export it.",
            err=True,
        )
        return False
    return True


__all__ = [
    "check_groq_key",
    "common_options",
    "load_configuration",
    "resolve_data_path",
    "resolve_tags_path",
    "validate_paths",
]
