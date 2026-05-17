"""Run subcommand — standalone click command registered via ``cli.add_command``.

Drives the full pipeline (stages 1-10) or selected types.  Supports
``--force`` for destructive re-inference and ``--tui``/``--no-tui``
for interactive mode control.
"""

from __future__ import annotations

import sys
from typing import Optional

import click
from orchestration.config import (
    check_groq_key,
    common_options,
    resolve_data_path,
    resolve_tags_path,
    validate_paths,
)
from orchestration.runner import resolve_target_stage
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
@click.option(
    "--limit",
    type=int,
    default=0,
    show_default=True,
    help="Limit processing to N tags with exemplars (0=all). "
    "Tags with the fewest exemplars are selected first.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Delete existing artifacts before re-inferring. Requires --type.",
)
@click.option(
    "--tui/--no-tui",
    "tui_mode",
    default=None,
    help="Force TUI or CLI review mode (default: auto-detect).",
)
@click.option(
    "--interactive/--no-interactive",
    "interactive_mode",
    default=None,
    hidden=True,
    help="Alias for --tui/--no-tui.",
)
@common_options
@click.pass_context
def run_cmd(
    ctx: click.Context,
    types: tuple[str, ...],
    all_flag: bool,
    limit: int,
    force: bool,
    tui_mode: Optional[bool],
    interactive_mode: Optional[bool],
    dry_run: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Run pipeline stages with HITL validation between inference stages."""
    if types and all_flag:
        click.echo("Error: --type and --all are mutually exclusive.", err=True)
        sys.exit(1)

    if force and not types:
        click.echo("Error: --force requires --type.", err=True)
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

    # Resolve tui_mode from --interactive alias if --tui was not set
    if tui_mode is None and interactive_mode is not None:
        tui_mode = interactive_mode

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
        if force:
            click.echo("  Force: enabled")
        return

    run_sequence(types, ctx_obj=obj, limit=limit, force=force, tui_mode=tui_mode)


# ── Public helpers (used by default.py) ─────────────────────────────────────


def run_sequence(
    types: tuple[str, ...],
    ctx_obj: dict | None = None,
    limit: int = 0,
    force: bool = False,
    tui_mode: Optional[bool] = None,
) -> None:
    """Run pipeline from current state through target stage.

    Owns its own DuckDB connection lifecycle — callers should NOT
    pass or manage a connection.  Resolves the initial state (fresh or
    resume via *ctx_obj* flags), creates config, and delegates to
    :func:`runner.run_pipeline` or the Textual TUI.

    When running in TUI mode, the init connection is closed before
    launching the TUI (the TUI opens its own connection).
    """
    from config.config import Config
    from orchestration.resume import handle_reset, resolve_state
    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        env_file = ctx_obj.get("env_file") if ctx_obj else None
        resume = bool(ctx_obj and ctx_obj.get("resume"))

        # ── No-resume: clear old session state before resolve ────────────────
        if not resume:
            handle_reset(con)

        # ── Resolve state (config validation for --resume happens here, safe) ─
        state = resolve_state(
            con,
            resume=resume,
            force_resume=bool(ctx_obj and ctx_obj.get("force_resume")),
            env_file=env_file,
        )

        # ── Force mode: delete artifacts at chosen level, then re-infer ──────
        if force and types:
            _force_reset_for_types(con, types)
            # Reload state from DB to pick up current_stage set by force reset
            from orchestration.state import WorkflowState
            from persistence.state_repository import load_state

            state = WorkflowState.from_state_dict(load_state(con))
        config = Config.from_env()

        target = resolve_target_stage(types)

        if _resolve_interactive(tui_mode, types):
            _launch_tui(state, config, target_stage=target, limit=limit)
            return

        from orchestration.runner import run_pipeline

        final_state = run_pipeline(con, state, config, target_stage=target, limit=limit)
        logger.debug(
            "Pipeline complete",
            extra={"final_stage": final_state.current_stage},
        )
    finally:
        if con is not None:
            con.close()


# ── Interactive mode resolution ──────────────────────────────────────────────


def _resolve_interactive(tui_mode: Optional[bool], types: tuple[str, ...]) -> bool:
    """Determine whether to use TUI or CLI mode.

    Priority:
      1. ``--tui`` → True
      2. ``--no-tui`` → False
      3. Auto (default) → True only if in a TTY and no --type specified
         (full pipeline review).
    """
    if tui_mode is not None:
        return tui_mode
    return not types and sys.stdout.isatty() and sys.stdin.isatty()


# ── Force-reset logic ────────────────────────────────────────────────────────


def _force_reset_for_types(con, types: tuple[str, ...]) -> None:
    """Delete all entities at and below the specified types.

    For each type in *types*, deletes every entity of that type and all
    downstream dependent types.  Operates as a soft-delete: sets
    ``status = 'rejected'``, removes edges, clears inference status, and
    invalidates embedding cache entries.

    After deletion, resets ``current_stage`` to the lowest inference stage
    needed and marks all ontology tags as dirty.
    """
    from graph import rebuild_graph
    from persistence.embedding_cache import invalidate_entity
    from persistence.state_updates import set_current_stage, update_dirty_flag

    # Determine what to delete
    delete_codes = "code" in types
    delete_themes = "theme" in types or delete_codes
    delete_interpretations = (
        "interpretation" in types or "theme" in types or delete_codes
    )

    con.execute("BEGIN TRANSACTION")

    try:
        # ── Delete interpretations ──────────────────────────────────────
        if delete_interpretations:
            interp_ids = con.execute(
                "SELECT id FROM nodes WHERE type = 'interpretation'"
            ).fetchall()
            for (iid,) in interp_ids:
                _delete_edges_for(con, iid, "interpretation")
                con.execute(
                    "UPDATE nodes SET status = 'rejected', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [iid],
                )
                con.execute(
                    "DELETE FROM inference_status WHERE entity_id = ?", [str(iid)]
                )
                invalidate_entity(con, str(iid), "interpretation")

        # ── Delete themes ───────────────────────────────────────────────
        if delete_themes:
            theme_ids = con.execute(
                "SELECT id FROM nodes WHERE type = 'theme'"
            ).fetchall()
            for (tid,) in theme_ids:
                _delete_edges_for(con, tid, "theme")
                con.execute(
                    "UPDATE nodes SET status = 'rejected', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [tid],
                )
                con.execute(
                    "DELETE FROM inference_status WHERE entity_id = ?", [str(tid)]
                )
                invalidate_entity(con, str(tid), "theme")

        # ── Delete codes ────────────────────────────────────────────────
        if delete_codes:
            code_ids = con.execute(
                "SELECT id FROM nodes WHERE type = 'code'"
            ).fetchall()
            for (cid,) in code_ids:
                _delete_edges_for(con, cid, "code")
                con.execute(
                    "UPDATE nodes SET status = 'rejected', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [cid],
                )
                con.execute(
                    "DELETE FROM inference_status WHERE entity_id = ?", [str(cid)]
                )
                invalidate_entity(con, str(cid), "code")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    # ── Set dirty flags for all tags ────────────────────────────────────
    tag_rows = con.execute(
        "SELECT DISTINCT tag FROM nodes WHERE tag IS NOT NULL"
    ).fetchall()
    for (tag,) in tag_rows:
        update_dirty_flag(con, tag, True)

    # ── Reset current_stage ─────────────────────────────────────────────
    if delete_interpretations:
        set_current_stage(con, 8)  # infer_interpretations
    if delete_themes:
        set_current_stage(con, 6)  # infer_themes
    if delete_codes:
        set_current_stage(con, 4)  # infer_codes

    rebuild_graph()


# ── TUI launcher ─────────────────────────────────────────────────────────────


def _launch_tui(
    state,
    config,
    target_stage: int = 10,
    limit: int = 0,
) -> None:
    """Launch the Textual TUI for interactive pipeline execution.

    The TUI opens and manages its own DuckDB connection.  The init
    connection from :func:`run_sequence` is already closed before
    this function is called.

    Args:
        state: Workflow state.
        config: Pipeline configuration.
        target_stage: Stop after this stage (default 10 = full pipeline).
        limit: Tag limit for processing.
    """
    # Pre-warm tqdm multiprocessing lock before TUI starts.
    import tqdm as _tqdm

    _tqdm.tqdm(total=0, disable=True)

    from hitl.shared import tui_mode
    from utils.logging import suppress_stderr_logging

    try:
        from hitl.tui import AnalystTUI

        app = AnalystTUI(state, config, limit=limit, target_stage=target_stage)
        try:
            with suppress_stderr_logging(), tui_mode():
                app.run()
        finally:
            app.close()
    except ImportError as exc:
        logger.warning(
            "Textual not available; falling back to CLI pipeline",
            extra={"error": str(exc)},
        )
        from orchestration.runner import run_pipeline
        from persistence.duckdb_init import init_or_migrate

        con = init_or_migrate()
        try:
            run_pipeline(con, state, config, target_stage=target_stage, limit=limit)
        finally:
            con.close()


__all__ = ["run_cmd", "run_sequence"]


# ── Edge deletion helpers ─────────────────────────────────────────────────────


def _delete_edges_for(con, node_id: int, node_type: str) -> None:
    """Delete all graph edges incident to *node_id*.

    Removes both incoming and outgoing edges whose type is relevant
    to the given *node_type*.
    """
    if node_type == "interpretation":
        con.execute(
            "DELETE FROM edges WHERE source_id = ? "
            "AND edge_type IN ('spans', 'derived-from')",
            [node_id],
        )
        con.execute(
            "DELETE FROM edges WHERE target_id = ? " "AND edge_type = 'derived-from'",
            [node_id],
        )
    elif node_type == "theme":
        con.execute(
            "DELETE FROM edges WHERE source_id = ? "
            "AND edge_type IN ('composed-of', 'derived-from')",
            [node_id],
        )
        con.execute(
            "DELETE FROM edges WHERE target_id = ? "
            "AND edge_type IN ('spans', 'derived-from')",
            [node_id],
        )
    elif node_type == "code":
        con.execute(
            "DELETE FROM edges WHERE source_id = ? "
            "AND edge_type IN ('contains', 'derived-from')",
            [node_id],
        )
        con.execute(
            "DELETE FROM edges WHERE target_id = ? "
            "AND edge_type IN ('composed-of', 'derived-from')",
            [node_id],
        )
