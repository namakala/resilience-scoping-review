"""Dual-pane entity browser widget for HITL review TUI.

Displays a list of entities (codes, themes, or interpretations) on the
left and a detail pane on the right.  Supports approve, reject, edit,
merge, and split actions via keybindings passed up to the parent app.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import duckdb
from hitl.queries_codes import get_all_codes
from hitl.queries_interpretations import get_all_interpretations
from hitl.queries_themes import get_all_themes
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

STATUS_ICONS = {
    "draft": "\u25c7",
    "pending": "\u25cb",
    "approved": "\u2713",
    "merged": "\u2295",
    "rejected": "\u2717",
}


class EntityBrowser(Widget):
    """Dual-pane browser for codes, themes, or interpretations.

    The left pane shows a scrollable list of entities with status
    icons.  The right pane shows full detail for the selected entity.

    Actions (approve, reject, edit, merge, split) are dispatched via
    methods that bubble up to the parent App.
    """

    can_focus = True
    BINDINGS = [
        Binding("e", "edit_entity", "Edit", show=True),
        Binding("a", "approve_entity", "Approve", show=True),
        Binding("r", "reject_entity", "Reject", show=True),
        Binding("m", "merge_entity", "Merge", show=True),
        Binding("s", "split_entity", "Split", show=True),
    ]

    DEFAULT_CSS = """
    EntityBrowser {
        height: 100%;
    }

    #entity-browser-horizontal {
        height: 1fr;
    }

    #entity-list-view {
        width: 35%;
        height: 100%;
        border: solid $primary;
    }

    #entity-detail {
        width: 65%;
        height: 100%;
        border: solid $accent;
        overflow-y: auto;
        padding: 0 1;
    }

    #entity-detail-content {
        height: auto;
    }
    """

    def __init__(
        self,
        entity_type: str,
        db_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.entity_type = entity_type
        self._db_path = db_path
        self.limited_tags: list[str] | None = None
        self._all_entities: list[dict[str, Any]] = []
        self._selected_index: int = 0
        self._refreshing: bool = False
        self._needs_refresh: bool = False

    # ── Diagnostics ────────────────────────────────────────────────

    def _debug_log(self, message: str) -> None:
        """Log to AnalystTUI debug log if PYTHONFAULTHANDLER is set."""
        if not os.getenv("PYTHONFAULTHANDLER"):
            return
        try:
            if hasattr(self.app, "_debug_log"):
                self.app._debug_log(f"[EntityBrowser/{self.entity_type}] {message}")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Horizontal(id="entity-browser-horizontal"):
            yield ListView(id="entity-list-view")
            with VerticalScroll(id="entity-detail"):
                yield Static(id="entity-detail-content")

    # ── Connection ──────────────────────────────────────────────────

    def _con(self) -> duckdb.DuckDBPyConnection:
        """Get or create a DuckDB connection."""
        from persistence.duckdb_connection import get_connection

        return get_connection(self._db_path)

    # ── Data refresh ────────────────────────────────────────────────

    async def refresh_entities(self) -> None:
        """Re-query the database and rebuild the entity list."""
        if self._refreshing:
            self._debug_log("refresh_entities: already running, queueing retry")
            self._needs_refresh = True
            return
        self._refreshing = True
        self._needs_refresh = False
        try:
            try:
                con = self._con()
            except Exception as exc:
                self._debug_log(f"refresh_entities: con() failed: {exc}")
                self._all_entities = []
                await self._rebuild_list()
                return

            try:
                if self.entity_type == "code":
                    all_entities = get_all_codes(con)
                elif self.entity_type == "theme":
                    all_entities = get_all_themes(con)
                elif self.entity_type == "interpretation":
                    all_entities = get_all_interpretations(con)
                else:
                    all_entities = []
                self._debug_log(
                    f"refresh_entities: fetched {len(all_entities)} entities"
                )
            except Exception as exc:
                self._debug_log(f"refresh_entities: query failed: {exc}")
                all_entities = []
            finally:
                con.close()

            if self.limited_tags is not None:
                pre = len(all_entities)
                all_entities = [
                    e for e in all_entities if e.get("tag") in self.limited_tags
                ]
                self._debug_log(
                    f"refresh_entities: tag-filtered from {pre} to {len(all_entities)}"
                )

            self._all_entities = all_entities
            await self._rebuild_list()
        finally:
            self._refreshing = False

        if self._needs_refresh:
            self._debug_log("refresh_entities: retrying queued refresh")
            await self.refresh_entities()

    async def _rebuild_list(self) -> None:
        """Rebuild the ListView from _all_entities, skipping merged entities."""
        list_view = self.query_one("#entity-list-view", ListView)
        await list_view.clear()

        appended = 0
        for i, entity in enumerate(self._all_entities):
            status = entity.get("status", "draft")
            if status == "merged":
                continue
            icon = STATUS_ICONS.get(status, "?")
            name = entity.get(
                "name",
                entity.get("narrative", "unnamed"),
            )
            label = f"{icon} {name}"
            await list_view.append(
                ListItem(Label(label, markup=False), id=f"entity-{i}")
            )
            appended += 1
            if appended <= 5:
                self._debug_log(
                    f"_rebuild_list: appended #{i} name={name} status={status}"
                )

        self._debug_log(f"_rebuild_list: total appended={appended}")
        if not self._all_entities:
            self._debug_log("_rebuild_list: no entities, showing empty message")

        if self._all_entities:
            list_view.index = 0
            self._show_detail(0)
        else:
            detail = self.query_one("#entity-detail-content", Static)
            detail.update(
                "[dim]No entities to display. " "Run the pipeline first.[/dim]"
            )

    # ── Detail display ──────────────────────────────────────────────

    def _show_detail(self, index: int) -> None:
        """Update the right pane with detail for entity at *index*."""
        if not self._all_entities or index < 0:
            return
        if index >= len(self._all_entities):
            index = len(self._all_entities) - 1
            if index < 0:
                return

        entity = self._all_entities[index]
        self._selected_index = index
        self._debug_log(
            f"_show_detail: index={index} "
            f"id={entity.get('id')} name={entity.get('name','?')}"
        )

        content = self.query_one("#entity-detail-content", Static)
        lines: list[str] = []

        name = entity.get(
            "name",
            entity.get("narrative", "unnamed"),
        )
        status = entity.get("status", "draft")
        tag = entity.get("tag", "")
        definition = entity.get(
            "definition",
            entity.get("narrative", ""),
        )
        dj: dict = entity.get("data_json") or {}

        # ── Top section (above separator) ──
        lines.append(f"[bold cyan]{name}[/bold cyan]")
        lines.append(f"Status: [bold]{status}[/bold]")
        if tag:
            lines.append(f"Tag: [yellow]{tag}[/yellow]")
        lines.append("")
        lines.append("[bold]Definition:[/bold]")
        lines.append(definition)
        lines.append("")

        # Semantic neighbors
        try:
            con = self._con()
            neighbor_lines = self._show_neighbors(con, entity.get("id", 0))
            lines.extend(neighbor_lines)
            con.close()
        except Exception:
            pass

        # Universal separator
        lines.append("")
        lines.append("[dim]─" * 40 + "[/dim]")
        lines.append("")

        # ── Bottom section (below separator) ──
        if self.entity_type == "code":
            exemplar_ids: list = dj.get("exemplar_ids", [])
            quotes: dict = dj.get("supporting_quotes", {})
            lines.append(f"[bold]Exemplars ({len(exemplar_ids)}):[/bold]")
            for eid in exemplar_ids:
                quote = quotes.get(str(eid), "[no quote]")
                lines.append(f'  #{eid}: "{quote}"')

        elif self.entity_type == "theme":
            lines.append("[bold]Codes:[/bold]")
            try:
                con2 = self._con()
                from hitl.queries_themes import get_constituent_codes

                codes = get_constituent_codes(con2, entity.get("id", 0))
                con2.close()
                if codes:
                    for c in codes:
                        icon = STATUS_ICONS.get(c["status"], "?")
                        name = c.get("name", f"#{c.get('id', '?')}")
                        count = c.get("exemplar_count", 0)
                        ex_label = f"({count} exemplar{'s' if count != 1 else ''})"
                        lines.append(f"  {icon} {name} {ex_label}")
                else:
                    lines.append("  [dim]No constituent codes[/dim]")
            except Exception:
                lines.append("  [dim]Could not load codes[/dim]")

        elif self.entity_type == "interpretation":
            tag_spans: list = dj.get("tag_spans", [])
            lines.append("[bold]Tag Spans:[/bold] " f"{', '.join(tag_spans)}")
            key_insights: list = dj.get("key_insights", [])
            if key_insights:
                lines.append("[bold]Key Insights:[/bold]")
                for insight in key_insights:
                    lines.append(f"  \u2022 {insight}")
            lines.append("")
            lines.append("[bold]Themes:[/bold]")
            try:
                con3 = self._con()
                from hitl.queries_interpretations import get_interpretation_themes

                themes = get_interpretation_themes(con3, entity.get("id", 0))
                con3.close()
                if themes:
                    for t in themes:
                        icon = STATUS_ICONS.get(t["status"], "?")
                        t_name = t.get("name", f"#{t.get('id', '?')}")
                        t_tag = t.get("tag", "")
                        lines.append(f"  {icon} {t_name}  [yellow]{t_tag}[/yellow]")
                else:
                    lines.append("  [dim]No themes linked[/dim]")
            except Exception:
                lines.append("  [dim]Could not load themes[/dim]")

        content.update("\n".join(lines))
        # Scroll detail pane to top when switching entities.
        try:
            detail_scroll = self.query_one("#entity-detail", VerticalScroll)
            detail_scroll.scroll_home(animate=False)
        except Exception:
            pass

    # ── List selection ──────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list item selection — show detail."""
        if event.item and event.item.id:
            try:
                index = int(event.item.id.split("-")[1])
                self._show_detail(index)
            except (ValueError, IndexError):
                pass

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle list item highlight (cursor move)."""
        if event.item and event.item.id:
            try:
                index = int(event.item.id.split("-")[1])
                self._show_detail(index)
            except (ValueError, IndexError):
                pass

    # ── Entity access ───────────────────────────────────────────────

    def current_entity(self) -> Optional[dict[str, Any]]:
        """Return the currently selected entity dict, or None."""
        if 0 <= self._selected_index < len(self._all_entities):
            return self._all_entities[self._selected_index]
        return None

    def index_of(self, entity_id: int) -> int:
        """Return the list index for the given entity id."""
        for i, e in enumerate(self._all_entities):
            if e.get("id") == entity_id:
                return i
        return 0

    # ── Actions ─────────────────────────────────────────────────────

    async def action_approve(self) -> None:
        """Approve the currently selected entity."""
        entity = self.current_entity()
        if entity is None:
            return
        entity_id = entity.get("id")
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_approve

            action_approve(con, entity, self.entity_type, self._db_path)
            con.close()
            await self.refresh_entities()
            if entity_id is not None:
                self._restore_selection(entity_id)
        except Exception as exc:
            self._show_error(f"Approve failed: {exc}")

    async def action_reject(self) -> None:
        """Reject the currently selected entity."""
        entity = self.current_entity()
        if entity is None:
            return
        entity_id = entity.get("id")
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_reject

            action_reject(con, entity, self.entity_type, self._db_path)
            con.close()
            await self.refresh_entities()
            if entity_id is not None:
                self._restore_selection(entity_id)
        except Exception as exc:
            self._show_error(f"Reject failed: {exc}")

    async def action_edit(self, new_name: str, new_definition: str) -> None:
        """Edit the currently selected entity."""
        entity = self.current_entity()
        if entity is None:
            return
        entity_id = entity.get("id")
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_edit

            action_edit(
                con,
                entity,
                self.entity_type,
                new_name,
                new_definition,
                self._db_path,
            )
            con.close()
            await self.refresh_entities()
            if entity_id is not None:
                self._restore_selection(entity_id)
        except Exception as exc:
            self._show_error(f"Edit failed: {exc}")

    async def action_merge(self, target_id: int) -> None:
        """Merge current entity into the target, then show target's detail."""
        entity = self.current_entity()
        if entity is None:
            return
        source_name = entity.get(
            "name", entity.get("narrative", f"#{entity.get('id')}")
        )
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_merge

            action_merge(
                con,
                entity,
                target_id,
                self.entity_type,
                self._db_path,
            )
            con.close()

            # Look up target name for toast notification
            target_name = f"#{target_id}"
            try:
                con2 = self._con()
                row = con2.execute(
                    "SELECT name FROM nodes WHERE id = ?", [target_id]
                ).fetchone()
                if row:
                    target_name = row[0]
                con2.close()
            except Exception:
                pass

            self.app.notify(
                f"Merged '{source_name}' into '{target_name}'",
                severity="information",
                timeout=3,
            )
            await self.refresh_entities()
            self._restore_selection(target_id)
        except Exception as exc:
            self._show_error(f"Merge failed: {exc}")

    async def action_split(self, selected_theme_ids: list[int]) -> None:
        """Split an interpretation by selected theme ids."""
        entity = self.current_entity()
        if entity is None:
            return
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_split

            action_split(
                con,
                entity,
                selected_theme_ids,
                entity_type=self.entity_type,
                db_path=self._db_path,
            )
            con.close()
            await self.refresh_entities()
        except Exception as exc:
            self._show_error(f"Split failed: {exc}")

    # ── Selection restoration ────────────────────────────────────────

    def _restore_selection(self, entity_id: int) -> None:
        """Restore list selection to the entity with the given ID."""
        list_view = self.query_one("#entity-list-view", ListView)
        for i, entity in enumerate(self._all_entities):
            if entity.get("id") == entity_id:
                list_view.index = i
                self._show_detail(i)
                return

    # ── Error display ───────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        """Show an error in the detail pane."""
        content = self.query_one("#entity-detail-content", Static)
        current = content.content or ""
        error_block = f"\n\n[bold red]Error:[/bold red] {message}"
        content.update(f"{current}{error_block}")

    def _show_neighbors(self, con, entity_id: int) -> list[str]:
        """Return rich-text lines for up to 3 semantic neighbors."""
        lines = []
        try:
            if self.entity_type == "code":
                from hitl.queries_codes import get_neighbors_code

                neighbors = get_neighbors_code(con, entity_id, k=3)
            elif self.entity_type == "theme":
                from hitl.queries_themes import get_neighbors_theme

                neighbors = get_neighbors_theme(con, entity_id, k=3)
            elif self.entity_type == "interpretation":
                from hitl.queries_interpretations import get_neighbors_interpretation

                neighbors = get_neighbors_interpretation(con, entity_id, k=3)
            else:
                return []
        except Exception:
            return []

        if not neighbors:
            lines.append("[dim]No similar entities found.[/dim]")
        else:
            lines.append("[bold]Semantic Neighbors:[/bold]")
            for nid, score, name in neighbors:
                pct = score * 100
                lines.append(f"  #{nid}  {name}  [green]{pct:.1f}%[/green]")
        return lines


__all__ = ["EntityBrowser"]
