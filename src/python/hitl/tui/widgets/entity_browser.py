"""Dual-pane entity browser widget for HITL review TUI.

Displays a list of entities (codes, themes, or interpretations) on the
left and a detail pane on the right.  Supports approve, reject, edit,
merge, and split actions via keybindings passed up to the parent app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb
from hitl.queries_codes import get_all_codes
from hitl.queries_interpretations import get_all_interpretations
from hitl.queries_themes import get_all_themes
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

STATUS_ICONS = {
    "draft": "[d]",
    "pending": "[p]",
    "approved": "[a]",
    "merged": "[m]",
    "rejected": "[r]",
}


class EntityBrowser(Widget):
    """Dual-pane browser for codes, themes, or interpretations.

    The left pane shows a scrollable list of entities with status
    icons.  The right pane shows full detail for the selected entity.

    Actions (approve, reject, edit, merge, split) are dispatched via
    methods that the parent App can call — or bound directly in the
    App's keybindings.
    """

    DEFAULT_CSS = """
    EntityBrowser {
        height: 100%;
    }

    #entity-list {
        width: 35%;
        height: 100%;
        border: solid $primary;
        overflow-y: auto;
    }

    #entity-detail {
        width: 65%;
        height: 100%;
        border: solid $accent;
        overflow-y: auto;
        padding: 0 1;
    }

    #entity-list-view {
        height: auto;
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

    def compose(self) -> ComposeResult:
        with Horizontal():
            with VerticalScroll(id="entity-list"):
                yield ListView(id="entity-list-view")
            with VerticalScroll(id="entity-detail"):
                yield Static(id="entity-detail-content")

    def on_mount(self) -> None:
        """No-op; the parent app triggers refresh explicitly when
        the review tab is enabled."""

    # ── Connection ──────────────────────────────────────────────────

    def _con(self) -> duckdb.DuckDBPyConnection:
        """Get or create a DuckDB connection."""
        from persistence.duckdb_connection import get_connection

        return get_connection(self._db_path)

    # ── Data refresh ────────────────────────────────────────────────

    async def refresh_entities(self) -> None:
        """Re-query the database and rebuild the entity list."""
        try:
            con = self._con()
        except Exception:
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
        except Exception:
            all_entities = []
        finally:
            con.close()

        if self.limited_tags is not None:
            all_entities = [
                e for e in all_entities if e.get("tag") in self.limited_tags
            ]

        self._all_entities = all_entities
        await self._rebuild_list()

    async def _rebuild_list(self) -> None:
        """Rebuild the ListView from _all_entities."""
        list_view = self.query_one("#entity-list-view", ListView)
        await list_view.clear()

        for i, entity in enumerate(self._all_entities):
            status = entity.get("status", "draft")
            icon = STATUS_ICONS.get(status, "[?]")
            name = entity.get(
                "name",
                entity.get("narrative", "unnamed"),
            )
            label = Text(f"{icon} {name}")
            await list_view.append(ListItem(Static(label), id=f"entity-{i}"))

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

        lines.append(f"[bold cyan]{name}[/bold cyan]")
        lines.append(f"Status: [bold]{status}[/bold]")
        if tag:
            lines.append(f"Tag: [yellow]{tag}[/yellow]")
        lines.append("")
        lines.append("[bold]Definition:[/bold]")
        lines.append(definition)
        lines.append("")

        if self.entity_type == "code":
            exemplar_ids: list = dj.get("exemplar_ids", [])
            quotes: dict = dj.get("supporting_quotes", {})
            lines.append(f"[bold]Exemplars ({len(exemplar_ids)}):[/bold]")
            for i, eid in enumerate(exemplar_ids):
                if i >= 3:
                    lines.append(
                        f"  [dim]... and " f"{len(exemplar_ids) - 3} more[/dim]"
                    )
                    break
                quote = quotes.get(str(eid), "")
                truncated = quote[:80] + "..." if len(quote) > 80 else quote
                lines.append(f'  #{eid}: "{truncated}"')

        elif self.entity_type == "theme":
            code_ids: list = dj.get("code_ids", [])
            lines.append(f"[bold]Codes ({len(code_ids)}):[/bold]")
            for cid in code_ids:
                lines.append(f"  Code #{cid}")

        elif self.entity_type == "interpretation":
            tag_spans: list = dj.get("tag_spans", [])
            lines.append("[bold]Tag Spans:[/bold] " f"{', '.join(tag_spans)}")
            key_insights: list = dj.get("key_insights", [])
            if key_insights:
                lines.append("[bold]Key Insights:[/bold]")
                for insight in key_insights:
                    lines.append(f"  • {insight}")

        lines.append("")
        lines.append("[dim]─" * 40 + "[/dim]")
        lines.append("[dim][e] Edit  [Enter] Approve  " "[r] Reject  [m] Merge[/dim]")
        if self.entity_type == "interpretation":
            lines.append("[dim][s] Split[/dim]")

        content.update("\n".join(lines))

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
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_approve

            action_approve(con, entity, self.entity_type, self._db_path)
            con.close()
            await self.refresh_entities()
        except Exception as exc:
            self._show_error(f"Approve failed: {exc}")

    async def action_reject(self) -> None:
        """Reject the currently selected entity."""
        entity = self.current_entity()
        if entity is None:
            return
        try:
            con = self._con()
            from hitl.tui.actions.handlers import action_reject

            action_reject(con, entity, self.entity_type, self._db_path)
            con.close()
            await self.refresh_entities()
        except Exception as exc:
            self._show_error(f"Reject failed: {exc}")

    async def action_edit(self, new_name: str, new_definition: str) -> None:
        """Edit the currently selected entity."""
        entity = self.current_entity()
        if entity is None:
            return
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
        except Exception as exc:
            self._show_error(f"Edit failed: {exc}")

    async def action_merge(self, target_id: int) -> None:
        """Merge current entity into the target."""
        entity = self.current_entity()
        if entity is None:
            return
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
            await self.refresh_entities()
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

    # ── Error display ───────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        """Show an error in the detail pane."""
        content = self.query_one("#entity-detail-content", Static)
        current = content.renderable or ""
        error_block = f"\n\n[bold red]Error:[/bold red] {message}"
        content.update(f"{current}{error_block}")


__all__ = ["EntityBrowser"]
