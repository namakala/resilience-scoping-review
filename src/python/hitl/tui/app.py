"""Main Textual TUI application for the qualitative thematic analysis
pipeline.

Provides a tabbed interface: a log tab for pipeline progress and
entity review tabs (Codes, Themes, Interpretations) that become
enabled as the pipeline reaches review stages.
"""

from __future__ import annotations

import asyncio
import time as _time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
from config.config import Config
from hitl.tui.widgets.entity_browser import EntityBrowser
from hitl.tui.widgets.modals import EditModal, MergeModal, SplitModal
from orchestration.state import WorkflowState
from orchestration.state_rules import STAGE_NAMES
from persistence.duckdb_connection import DEFAULT_DB_PATH
from persistence.state_repository import load_state, save_state
from rich.text import Text as RichText
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Footer, Header, TabbedContent, TabPane, TextArea
from textual.widgets._progress_bar import ProgressBar
from textual.widgets._static import Static
from utils.exceptions import StateError

# ── Custom messages ──────────────────────────────────────────────────


class PipelineLog(Message):
    """Posted to add a log line to the log tab."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class EnableTab(Message):
    """Posted to enable and switch to a tab."""

    def __init__(self, tab_id: str) -> None:
        super().__init__()
        self.tab_id = tab_id


class ProgressUpdate(Message):
    """Posted to update the progress bar in the Logs tab.

    When *total* is ``None`` the bar shows an indeterminate animation.
    When *total* is a positive integer the bar shows a determinate
    fraction ``completed / total``.
    """

    def __init__(self, total: int | None, completed: int, description: str) -> None:
        super().__init__()
        self.total = total
        self.completed = completed
        self.description = description


# ── Debug log path ──────────────────────────────────────────────────


def _resolve_debug_log_path(config: Config) -> Path:
    """Return the path for the TUI debug log file."""
    return config.export_output_path / "tui_debug.log"


# ── Main TUI App ─────────────────────────────────────────────────────


class AnalystTUI(App):
    """Textual TUI for the thematic analysis pipeline with HITL review."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #log-view {
        height: 1fr;
        border: solid $accent;
    }

    #progress-container {
        height: 3;
        dock: bottom;
        background: $surface;
    }

    #progress-description {
        text-style: bold;
        padding: 0 1;
    }

    #progress-bar {
        margin: 0 1;
    }

    EntityBrowser {
        height: 1fr;
    }
    """

    TITLE = "Resilience Scoping Review — Thematic Analysis"
    SUB_TITLE = "HITL Review TUI"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("e", "edit_entity", "Edit", show=True),
        Binding("a", "approve_entity", "Approve", show=True),
        Binding("r", "reject_entity", "Reject", show=True),
        Binding("m", "merge_entity", "Merge", show=True),
        Binding("s", "split_entity", "Split", show=True),
    ]

    def __init__(
        self,
        state: WorkflowState,
        config: Config,
        db_path: Path = DEFAULT_DB_PATH,
        limit: int = 0,
    ) -> None:
        super().__init__()
        from persistence.duckdb_init import init_or_migrate

        self._con = init_or_migrate(db_path)
        self._state = state
        self._config = config
        self._db_path = db_path
        self._limit = limit
        self._limited_tags: list[str] | None = None
        self._pipeline_done = False
        self._pipeline_stop = False
        self._review_artifact: Optional[str] = None
        self._pipeline_exc: Optional[Exception] = None
        self._worker = None
        self._debug_log_path: Path = _resolve_debug_log_path(config)
        self._debug_log("AnalystTUI.__init__ complete")

    def close(self) -> None:
        """Clean up the DuckDB connection."""
        if self._con is not None:
            self._con.close()
            self._con = None

    def compose(self) -> ComposeResult:
        self._debug_log("compose() called")
        yield Header()
        with TabbedContent(initial="logs"):
            with TabPane("Logs", id="logs"):
                yield TextArea(
                    id="log-view",
                    read_only=True,
                    show_line_numbers=False,
                    soft_wrap=True,
                    max_checkpoints=0,
                )
                yield Container(
                    Static(id="progress-description"),
                    ProgressBar(id="progress-bar"),
                    id="progress-container",
                )
            with TabPane("Codes", id="codes", disabled=True):
                yield EntityBrowser(entity_type="code", db_path=self._db_path)
            with TabPane("Themes", id="themes", disabled=True):
                yield EntityBrowser(entity_type="theme", db_path=self._db_path)
            with TabPane(
                "Interpretations",
                id="interpretations",
                disabled=True,
            ):
                yield EntityBrowser(
                    entity_type="interpretation",
                    db_path=self._db_path,
                )
        yield Footer()

    def on_mount(self) -> None:
        """Start the pipeline in a background thread."""
        self._debug_log("on_mount fired; posting Pipeline starting")
        self._post_log("[bold blue]Pipeline starting...[/bold blue]")
        self._worker = self.run_worker(
            self._run_pipeline_async(),
            exclusive=True,
            group="pipeline",
        )

    def on_unmount(self) -> None:
        """Signal the pipeline thread to stop when the TUI exits."""
        self._pipeline_stop = True
        self._debug_log("on_unmount fired; pipeline stop signaled")

    # ── Message handlers ─────────────────────────────────────────────

    def _debug_log(self, message: str) -> None:
        """Write a timestamped message to the TUI debug log file."""
        self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        with open(str(self._debug_log_path), "a") as f:
            f.write(f"[{ts}] {message}\n")

    def _append_log(self, plain: str) -> None:
        """Append a plain text line to the log TextArea and scroll to end."""
        try:
            log = self.query_one("#log-view", TextArea)
            existing = log.text
            log.text = f"{existing}{plain}\n" if existing else f"{plain}\n"
            log.scroll_end(animate=False)
        except Exception:
            self._debug_log(f"[_append_log fallback] {plain}")

    def _update_log(self, text: str) -> None:
        """Directly write to the log TextArea (main thread only)."""
        plain = RichText.from_markup(text).plain
        self._append_log(plain)

    def on_pipeline_log(self, msg: PipelineLog) -> None:
        """Write a log line to the log tab."""
        plain = RichText.from_markup(msg.text).plain
        self._append_log(plain)

    # ── Progress bar handlers ──────────────────────────────────────

    def _update_progress(
        self, total: int | None, completed: int, description: str
    ) -> None:
        """Update the progress bar and description (main thread only).

        When *total* is ``None`` the bar shows an indeterminate
        animation.  When *total* is a positive integer the bar shows
        a determinate fraction ``completed / total``.
        """
        try:
            pb = self.query_one("#progress-bar", ProgressBar)
            desc = self.query_one("#progress-description", Static)
            pb.total = total
            pb.progress = completed
            desc.update(description)
            if total is not None and total > 0:
                self._append_log(f"[{completed}/{total}] {description}")
            else:
                self._append_log(description)
        except Exception:
            self._debug_log(
                f"[_update_progress fallback] {description} " f"({completed}/{total})"
            )

    def on_progress_update(self, msg: ProgressUpdate) -> None:
        """Update the progress bar from a ProgressUpdate message."""
        self._update_progress(msg.total, msg.completed, msg.description)

    def on_enable_tab(self, msg: EnableTab) -> None:
        """Enable and switch to the given tab."""
        tabs = self.query_one(TabbedContent)
        tab = tabs.query_one(f"#{msg.tab_id}", TabPane)
        tab.disabled = False
        tabs.active = msg.tab_id
        # Trigger entity browser refresh on the main thread (where the
        # ``active_app`` ContextVar is available) so widget operations
        # like ``list_view.clear()`` don't raise LookupError.
        if msg.tab_id in ("codes", "themes", "interpretations"):
            self._schedule_review_tab_refresh(msg.tab_id)

    def _schedule_review_tab_refresh(self, tab_id: str) -> None:
        """Refresh the EntityBrowser for the given review tab."""
        artifact_type = {
            "codes": "code",
            "themes": "theme",
            "interpretations": "interpretation",
        }[tab_id]
        browser = self._entity_browser_for_type(artifact_type)
        if browser is not None:
            browser.limited_tags = self._limited_tags
            self._debug_log(f"_schedule_review_tab_refresh: tab_id={tab_id}")
            asyncio.create_task(browser.refresh_entities())
            browser.focus()

    def _post_log(self, text: str) -> None:
        """Post a PipelineLog message; fall back to direct widget update."""
        try:
            self.post_message(PipelineLog(text))
        except Exception:
            self.call_from_thread(self._update_log, text)

    def _make_progress_callback(self):
        """Return a thread-safe progress callback with throttling.

        The returned closure posts ``ProgressUpdate`` messages to the
        main thread's message queue.  Falls back to
        ``call_from_thread`` if ``post_message`` fails.

        Throttling: updates with < 1% change in progress are skipped
        (except the final ``completed == total`` update) to avoid
        flooding the message queue from tight loops.
        """
        last_pct = -1

        def _cb(total: int | None, completed: int, description: str) -> None:
            nonlocal last_pct
            if total is not None and total > 0:
                pct = int(100 * completed / total)
                if completed < total and pct == last_pct:
                    return
                last_pct = pct
            try:
                self.post_message(ProgressUpdate(total, completed, description))
            except Exception:
                self.call_from_thread(
                    self._update_progress, total, completed, description
                )

        return _cb

    # ── Pipeline execution (in thread executor) ─────────────────────

    async def _run_pipeline_async(self) -> None:
        """Run the pipeline in a thread executor.

        The pipeline creates its own DuckDB connection inside the
        executor thread, avoiding the cross-thread ``fds_to_keep``
        error that occurs when a connection is shared across threads.
        """
        self._debug_log("pipeline started (threaded)")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._run_pipeline_sync)
        except Exception as exc:
            self._debug_log(f"pipeline failed: {exc}")
            self._debug_log(traceback.format_exc())
            self._pipeline_exc = exc
            self._post_log(f"[bold red]Pipeline failed: {exc}[/bold red]")
            self._post_log(
                "[bold red]Check the logs above for "
                "details. Press q to quit.[/bold red]"
            )

    def _run_pipeline_sync(self) -> None:
        """Run pipeline stages synchronously in a worker thread.

        Creates its own DuckDB connection to avoid sharing ``self._con``
        across threads.  All ``_post_log`` / ``_debug_log`` calls are
        thread-safe.  Blocking calls use ``_time.sleep()`` for polling;
        UI updates are scheduled on the event loop via
        :func:`asyncio.run_coroutine_threadsafe`.
        """
        from inference.code_inference import infer_codes
        from inference.code_node_creation import create_code_nodes
        from inference.create_theme_nodes import create_theme_nodes
        from inference.interpretation_creation import create_interpretation_nodes
        from inference.interpretation_synthesis import synthesize_interpretations
        from inference.seed_inference_status import seed_pending_exemplars
        from inference.theme_inference import infer_themes
        from ontology.cache import build_traversal_cache
        from ontology.dag import build_tag_dag, validate_tag_dag
        from persistence.duckdb_init import init_or_migrate
        from persistence.loaders import load_exemplars, load_keywords, load_tags
        from semantic.embedding_generation import (
            generate_code_embeddings,
            generate_exemplar_embeddings,
            generate_interpretation_embeddings,
            generate_theme_embeddings,
        )
        from semantic.index_builder import build_index
        from semantic.keyword_extraction import extract_keywords

        con = init_or_migrate(self._db_path)
        state = self._state

        self._debug_log("pipeline started (sync, threaded)")

        try:
            progress_cb = self._make_progress_callback()
            from inference.llm_logger import set_llm_log_path

            set_llm_log_path(self._config.export_output_path / "llm_output.json")
            self._enable_artifact_tabs(con)
            while state.current_stage <= 10:
                if self._pipeline_stop:
                    self._debug_log("pipeline stop requested — breaking stage loop")
                    break
                stage = state.current_stage
                stage_name = STAGE_NAMES.get(stage, f"stage_{stage}")

                self._debug_log(f"stage {stage} ({stage_name}) started")
                self._post_log(
                    f"[bold blue]Stage {stage} " f"({stage_name}) started[/bold blue]"
                )
                progress_cb(None, 0, stage_name)
                start = _time.monotonic()

                try:
                    if stage == 1:
                        try:
                            self._debug_log("stage 1: load_exemplars()...")
                            _ = load_exemplars()
                            self._debug_log("stage 1: load_exemplars() OK")
                        except Exception as exc:
                            self._debug_log(
                                "stage 1: load_exemplars() " f"FAILED: {exc}"
                            )
                            self._debug_log(traceback.format_exc())
                            raise

                        try:
                            self._debug_log("stage 1: load_tags()...")
                            _ = load_tags()
                            self._debug_log("stage 1: load_tags() OK")
                        except Exception as exc:
                            self._debug_log("stage 1: load_tags() " f"FAILED: {exc}")
                            self._debug_log(traceback.format_exc())
                            raise

                        try:
                            self._debug_log("stage 1: load_keywords()...")
                            _ = load_keywords()
                            self._debug_log("stage 1: load_keywords() OK")
                        except Exception as exc:
                            self._debug_log(
                                "stage 1: load_keywords() " f"FAILED: {exc}"
                            )
                            self._debug_log(traceback.format_exc())
                            raise

                        try:
                            self._debug_log("stage 1: " "extract_keywords()...")
                            extract_keywords(con, progress_callback=progress_cb)
                            self._debug_log("stage 1: " "extract_keywords() OK")
                        except Exception as exc:
                            self._debug_log(
                                "stage 1: extract_keywords() " f"FAILED: {exc}"
                            )
                            self._debug_log(traceback.format_exc())
                            raise

                        self._debug_log("stage 1: build_tag_dag()...")
                        G = build_tag_dag()
                        self._debug_log("stage 1: build_tag_dag() OK")

                        self._debug_log("stage 1: validate_tag_dag()...")
                        validate_tag_dag(G)
                        self._debug_log("stage 1: validate_tag_dag() OK")
                        self._post_log(
                            "[green]Data load and validation " "complete[/green]"
                        )

                    elif stage == 2:
                        generate_exemplar_embeddings(con, progress_callback=progress_cb)
                        self._post_log(
                            "[green]Embedding generation " "complete[/green]"
                        )

                    elif stage == 3:
                        kw_lf = load_keywords()
                        # Build exemplar content map for enriched BM25 index
                        ex_lf = load_exemplars().select(["id", "content"]).collect()
                        exemplar_content_map = {
                            row["id"]: row["content"]
                            for row in ex_lf.iter_rows(named=True)
                        }
                        build_index(
                            kw_lf,
                            tokenizer_config=(self._config.bm25_tokenizer_config),
                            exemplar_content_map=exemplar_content_map,
                        )
                        build_traversal_cache()
                        self._post_log("[green]Index build complete[/green]")

                    elif stage == 4:
                        if self._limit > 0 and self._limited_tags is None:
                            from orchestration.runner import select_limited_tags

                            self._limited_tags = select_limited_tags(self._limit)
                        seed_pending_exemplars(con)
                        codes = infer_codes(
                            con,
                            tags=self._limited_tags,
                            progress_callback=progress_cb,
                        )
                        if codes:
                            create_code_nodes(
                                con,
                                codes,
                                db_path=DEFAULT_DB_PATH,
                            )
                            generate_code_embeddings(con, progress_callback=progress_cb)
                        self._post_log(
                            f"[green]Code inference complete "
                            f"({len(codes) if codes else 0} "
                            f"codes)[/green]"
                        )

                    elif stage == 5:
                        self._handle_review_stage("code", con=con)
                        self._post_log("[green]Code review complete[/green]")

                    elif stage == 6:
                        for (
                            tag,
                            is_dirty,
                        ) in state.dirty_flags.items():
                            if is_dirty and (
                                self._limited_tags is None or tag in self._limited_tags
                            ):
                                themes = infer_themes(
                                    con,
                                    tag=tag,
                                    progress_callback=progress_cb,
                                )
                                if themes:
                                    create_theme_nodes(
                                        con,
                                        themes,
                                        tag=tag,
                                        db_path=DEFAULT_DB_PATH,
                                    )
                                    generate_theme_embeddings(
                                        con, progress_callback=progress_cb
                                    )
                        self._post_log("[green]Theme inference " "complete[/green]")

                    elif stage == 7:
                        self._handle_review_stage("theme", con=con)
                        self._post_log("[green]Theme review " "complete[/green]")

                    elif stage == 8:
                        interpretations = synthesize_interpretations(
                            con,
                            tags=self._limited_tags,
                            progress_callback=progress_cb,
                        )
                        if interpretations:
                            create_interpretation_nodes(
                                con,
                                interpretations,
                                db_path=DEFAULT_DB_PATH,
                            )
                            generate_interpretation_embeddings(
                                con, progress_callback=progress_cb
                            )
                        count = len(interpretations) if interpretations else 0
                        self._post_log(
                            "[green]Interpretation synthesis "
                            "complete "
                            f"({count} "
                            "interpretations)[/green]"
                        )

                    elif stage == 9:
                        self._handle_review_stage("interpretation", con=con)
                        self._post_log(
                            "[green]Interpretation review " "complete[/green]"
                        )

                    elif stage == 10:
                        from orchestration.export import export_all

                        export_all(
                            con,
                            state,
                            self._config,
                            self._db_path,
                        )
                        self._post_log("[bold green]Export " "complete![/bold green]")
                        break

                except Exception as exc:
                    self._debug_log(f"stage {stage} failed: {exc}")
                    self._debug_log(traceback.format_exc())
                    self._post_log(
                        f"[bold red]Stage {stage} failed: " f"{exc}[/bold red]"
                    )
                    raise

                elapsed = _time.monotonic() - start
                self._debug_log(
                    f"stage {stage} ({stage_name}) " f"completed in {elapsed:.1f}s"
                )
                self._post_log(
                    f"[green]Stage {stage} ({stage_name}) "
                    f"completed in {elapsed:.1f}s[/green]"
                )

                self._save_checkpoint(state, con=con)
                state.advance_stage()

            self._pipeline_done = True
            self._debug_log("pipeline complete — all stages done")
            self._post_log(
                "[bold green]All stages complete! " "Press q to exit.[/bold green]"
            )
            # Enable any tabs that have artifacts (handles --resume
            # and auto-advanced stages where EnableTab was never posted).
            try:
                self._enable_artifact_tabs(con)
            except Exception:
                self._debug_log("enable_artifact_tabs failed — non-fatal")
        finally:
            from inference.llm_logger import _entries as _llm_entries
            from inference.llm_logger import flush_llm_log

            flush_llm_log()
            self._debug_log(f"DIAG: LLM calls this run = {len(_llm_entries)}")
            con.close()

    # ── Review stage handling (synchronous, called from pipeline thread) ──

    def _handle_review_stage(self, artifact_type: str, con=None) -> None:
        """Enable the review tab and wait for user to finish.

        Synchronous version — called from the pipeline thread.
        Enables the tab via ``post_message`` (thread-safe) and then
        polls for pending items.  The EntityBrowser refresh happens
        on the main thread in :meth:`on_enable_tab` →
        :meth:`_schedule_review_tab_refresh`, where the ``active_app``
        ContextVar is properly set.
        """
        conn = con or self._con

        pending = self._query_pending(artifact_type, con=conn)
        if not pending:
            self._post_log(
                f"[yellow]No pending {artifact_type}s "
                f"to review; auto-advancing[/yellow]"
            )
            return

        tab_id = {
            "code": "codes",
            "theme": "themes",
            "interpretation": "interpretations",
        }[artifact_type]

        self.post_message(EnableTab(tab_id))
        self._review_artifact = artifact_type

        self._post_log(
            f"[bold yellow]Review {len(pending)} "
            f"{artifact_type}(s) in the '{tab_id}' tab. "
            f"Use keys: [e]dit, [a]pprove, [r]eject, "
            f"[m]erge[/bold yellow]"
        )

        # Polling loop — blocks the pipeline thread but leaves the
        # event loop free to process user input and render.
        _time.sleep(0.5)
        while True:
            if self._pipeline_stop:
                self._debug_log("pipeline stop requested — exiting review polling")
                break
            remaining = self._query_pending(artifact_type, con=conn)
            if not remaining:
                break
            _time.sleep(0.5)

        self._review_artifact = None

        # After code review, populate dirty flags for tags with approved codes
        # so stage 6 (theme inference) knows which tags to process.
        if artifact_type == "code":
            from persistence.state_updates import update_dirty_flag

            rows = conn.execute(
                "SELECT DISTINCT tag FROM nodes "
                "WHERE type = 'code' AND status = 'approved'"
            ).fetchall()
            for (tag,) in rows:
                update_dirty_flag(conn, tag, True)

        # Reload state after review (captures HITL mutations).
        # NOTE: current_stage from DB may be stale because
        # increment_user_action_count / update_dirty_flag previously
        # used load-modify-save that wrote back old current_stage.
        # The in-memory self._state.current_stage is authoritative.
        updated = load_state(con=self._con)
        new_state = WorkflowState.from_state_dict(updated)
        self._state.dirty_flags = new_state.dirty_flags
        self._state.user_action_count = new_state.user_action_count
        self._state.last_checkpoint = new_state.last_checkpoint
        self._state._extra_fields = (
            dict(new_state._extra_fields) if new_state._extra_fields else {}
        )

    def _query_pending(self, artifact_type: str, con=None) -> list:
        """Return list of pending entities for the given type.

        Uses *con* if provided, otherwise ``self._con``.
        """
        conn = con or self._con
        if artifact_type == "code":
            from hitl.queries_codes import get_pending_codes

            return get_pending_codes(conn)
        elif artifact_type == "theme":
            from hitl.queries_themes import get_pending_themes

            return get_pending_themes(conn)
        elif artifact_type == "interpretation":
            from hitl.queries_interpretations import get_pending_interpretations

            return get_pending_interpretations(conn)
        return []

    # ── Checkpoint ───────────────────────────────────────────────────

    def _enable_artifact_tabs(self, con) -> None:
        """Enable review tabs that have artifacts in the database.

        Queries each artifact type and posts EnableTab for any tab
        that has at least one entity node.  Safely handles the case
        where a tab is already enabled.
        """
        tab_ids = {
            "code": "codes",
            "theme": "themes",
            "interpretation": "interpretations",
        }
        for artifact_type, tab_id in tab_ids.items():
            count = con.execute(
                "SELECT COUNT(*) FROM nodes WHERE type = ?", [artifact_type]
            ).fetchone()[0]
            if count > 0:
                try:
                    self.post_message(EnableTab(tab_id))
                except Exception:
                    self._debug_log(
                        f"EnableTab({tab_id}) failed — tab may already be enabled"
                    )

    def _save_checkpoint(self, state: WorkflowState, con=None) -> None:
        """Persist workflow state to DuckDB with retry on transaction conflict.

        Uses *con* if provided, otherwise ``self._con``.
        Retries up to 3 times with exponential backoff to handle DuckDB
        transaction conflicts from concurrent state writes.
        """
        conn = con or self._con
        state.last_checkpoint = datetime.now(timezone.utc).isoformat()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                save_state(conn, state.to_state_dict())
                return
            except StateError as exc:
                if "Conflict on update" in str(exc) and attempt < max_retries - 1:
                    _time.sleep(0.1 * (attempt + 1))
                    self._debug_log(
                        f"State save conflict, retrying "
                        f"({attempt + 1}/{max_retries})..."
                    )
                    continue
                raise

    # ── Key handlers (main thread) ───────────────────────────────────

    def _entity_browser_for_type(self, artifact_type: str) -> Optional[EntityBrowser]:
        """Get the EntityBrowser widget for the given type."""
        tab_id = {
            "code": "codes",
            "theme": "themes",
            "interpretation": "interpretations",
        }[artifact_type]
        tabs = self.query_one(TabbedContent)
        try:
            tab = tabs.query_one(f"#{tab_id}", TabPane)
        except Exception:
            return None
        from typing import cast

        return cast(EntityBrowser, tab.query_one(EntityBrowser))

    def action_edit_entity(self) -> None:
        """Open an edit modal for the currently active entity."""
        active = self._get_active_review_tab()
        if not active:
            return
        browser = self._entity_browser_for_type(active)
        if browser is None:
            return
        entity = browser.current_entity()
        if entity is None:
            return

        name = entity.get(
            "name",
            entity.get("narrative", "unnamed"),
        )
        definition = entity.get(
            "definition",
            entity.get("narrative", ""),
        )

        def on_edit(result: Optional[tuple]) -> None:
            if result is None:
                return
            new_name, new_def = result
            browser.call_after_refresh(
                browser.action_edit,
                new_name or "",
                new_def or "",
            )

        self.push_screen(EditModal(name, definition, active), on_edit)

    async def action_approve_entity(self) -> None:
        """Approve the currently selected entity."""
        browser = self._get_active_browser()
        if browser:
            await browser.action_approve()

    async def action_reject_entity(self) -> None:
        """Reject the currently selected entity."""
        browser = self._get_active_browser()
        if browser:
            await browser.action_reject()

    def action_merge_entity(self) -> None:
        """Open merge modal for the currently active entity."""
        active = self._get_active_review_tab()
        if not active:
            return
        browser = self._entity_browser_for_type(active)
        if browser is None:
            return
        entity = browser.current_entity()
        if entity is None:
            return

        # Fetch candidates for merge
        try:
            con = self._get_db_con()
            candidates = self._get_merge_candidates(con, active, entity)
            con.close()
        except Exception:
            return

        current_id = entity.get("id", 0)

        def on_merge(result: Optional[int]) -> None:
            if result is None:
                return
            browser.call_after_refresh(browser.action_merge, result)

        self.push_screen(
            MergeModal(active, candidates, current_id),
            on_merge,
        )

    def action_split_entity(self) -> None:
        """Open split modal for an interpretation."""
        active = self._get_active_review_tab()
        if active != "interpretation":
            return
        browser = self._entity_browser_for_type("interpretation")
        if browser is None:
            return
        entity = browser.current_entity()
        if entity is None:
            return

        # Fetch themes for this interpretation via spans edges
        try:
            con = self._get_db_con()
            from hitl.queries_interpretations import get_interpretation_themes

            themes = get_interpretation_themes(con, entity["id"])
            con.close()
        except Exception:
            return

        if not themes:
            self._post_log(
                "[yellow]No themes found for this "
                "interpretation; cannot split[/yellow]"
            )
            return

        def on_split(result: Optional[list[int]]) -> None:
            if result is None:
                return
            browser.call_after_refresh(browser.action_split, result)

        self.push_screen(SplitModal(themes), on_split)

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_active_review_tab(self) -> Optional[str]:
        """Return the artifact type of the active review tab,
        or None."""
        tabs = self.query_one(TabbedContent)
        active = tabs.active
        mapping = {
            "codes": "code",
            "themes": "theme",
            "interpretations": "interpretation",
        }
        return mapping.get(active)

    def _get_active_browser(self) -> Optional[EntityBrowser]:
        """Return the EntityBrowser in the active tab, or None."""
        active = self._get_active_review_tab()
        if not active:
            return None
        return self._entity_browser_for_type(active)

    def _get_db_con(self) -> duckdb.DuckDBPyConnection:
        """Get a DuckDB connection for ad-hoc queries."""
        from persistence.duckdb_connection import get_connection

        return get_connection(self._db_path)

    def _get_merge_candidates(
        self,
        con: duckdb.DuckDBPyConnection,
        entity_type: str,
        entity: dict,
    ) -> list[dict]:
        """Return candidate entities for merge.

        Includes same-tag candidates plus cross-tag neighbors with
        similarity > 50%.  For themes, if no candidates are found,
        falls back to all draft themes across all tags.
        """
        tag = entity.get("tag", "")
        current_id = entity.get("id", 0)

        if entity_type == "code":
            from hitl.queries_codes import get_all_codes

            all_codes = get_all_codes(con, tag=tag)
            same_tag = [
                c
                for c in all_codes
                if c.get("id") != current_id and c.get("status") != "merged"
            ]
        elif entity_type == "theme":
            from hitl.queries_themes import get_other_draft_themes

            same_tag = get_other_draft_themes(con, current_id, tag)
        else:
            return []

        existing_ids = {c["id"] for c in same_tag}
        candidates = list(same_tag)

        # Cross-tag candidates — semantic neighbors with similarity > 50%.
        # Only offered for themes (codes must stay within their tag).
        if entity_type != "code":
            from hitl.queries import _get_neighbors

            neighbors = _get_neighbors(con, current_id, entity_type, k=10)
            for nid, score, name in neighbors:
                if nid != current_id and nid not in existing_ids and score > 0.5:
                    row = con.execute(
                        "SELECT id, name, tag, status FROM nodes WHERE id = ?",
                        [nid],
                    ).fetchone()
                    if row and row[3] != "merged":
                        candidates.append(
                            {
                                "id": row[0],
                                "name": name,
                                "tag": row[2],
                                "status": row[3],
                            }
                        )

        # Fallback: if no candidates at all, show all draft themes across all tags
        # This gives users a manual escape hatch when single-code themes block approval
        if not candidates and entity_type == "theme":
            rows = con.execute(
                "SELECT id, name, tag, status FROM nodes "
                "WHERE type = 'theme' AND status = 'draft' AND id != ? "
                "ORDER BY tag, name",
                [current_id],
            ).fetchall()
            for row in rows:
                candidates.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "tag": row[2],
                        "status": row[3],
                    }
                )

        return candidates

    def key_enter(self) -> None:
        """Enter quits when pipeline is done."""
        if self._pipeline_done:
            self.exit()


__all__ = ["AnalystTUI"]
