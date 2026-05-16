"""Modal screens for HITL review actions.

Provides EditModal, MergeModal, and SplitModal — pop-up screens
that collect user input before dispatching to action handlers.
"""

from __future__ import annotations

from typing import Any, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TextArea


class EditModal(ModalScreen[Optional[tuple[str, str]]]):
    """Modal for editing an entity's name and/or definition/narrative.

    Returns a (name, definition) tuple, or None if cancelled.
    Fields are pre-filled with current values.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        entity_name: str,
        entity_definition: str,
        entity_type: str,
    ) -> None:
        super().__init__()
        self._entity_name = entity_name
        self._entity_definition = entity_definition
        self._entity_type = entity_type

    def compose(self) -> ComposeResult:
        label_entity = self._entity_type.capitalize()
        yield Static(f"[bold]Edit {label_entity}[/bold]", id="edit-title")
        yield Static(f"Current name: {self._entity_name}")
        yield Label("New name (leave empty to keep):")
        yield Input(
            value="",
            placeholder=self._entity_name,
            id="edit-name-input",
        )
        yield Label(f"New {self._entity_type} definition/narrative:")
        yield TextArea(
            text="",
            id="edit-definition-input",
        )
        with Horizontal(classes="modal-buttons"):
            yield Button("Save", variant="primary", id="edit-save")
            yield Button("Cancel", variant="default", id="edit-cancel")

    CSS = """
    EditModal {
        align: center middle;
    }
    EditModal > Vertical, EditModal > Static, EditModal > Label,
    EditModal > TextArea, EditModal > Horizontal {
        width: 60;
    }
    #edit-title {
        text-align: center;
        padding: 1 0;
    }
    #edit-name-input {
        margin: 0 0 1 0;
    }
    #edit-definition-input {
        height: 10;
        margin: 0 0 1 0;
    }
    .modal-buttons {
        align-horizontal: center;
        height: 3;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-save":
            name = self.query_one("#edit-name-input", Input).value.strip()
            definition = self.query_one("#edit-definition-input", TextArea).text.strip()
            self.dismiss((name or None, definition or None))
        else:
            self.dismiss(None)


class MergeModal(ModalScreen[Optional[int]]):
    """Modal for selecting a target entity to merge into.

    Shows a list of candidate entities (same type, excluding self).
    Returns the target id, or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        entity_type: str,
        candidates: list[dict[str, Any]],
        current_id: int,
    ) -> None:
        super().__init__()
        self._entity_type = entity_type
        self._candidates = candidates
        self._current_id = current_id

    def compose(self) -> ComposeResult:
        label = self._entity_type.capitalize()
        yield Static(f"[bold]Merge {label} Into...[/bold]", id="merge-title")
        yield Static("Select the target entity to merge the current one into:")
        yield ListView(id="merge-list")
        with Horizontal(classes="modal-buttons"):
            yield Button("Cancel", variant="default", id="merge-cancel")

    CSS = """
    MergeModal {
        align: center middle;
    }
    MergeModal > Vertical, MergeModal > Static, MergeModal > ListView,
    MergeModal > Horizontal {
        width: 60;
    }
    #merge-title {
        text-align: center;
        padding: 1 0;
    }
    #merge-list {
        height: 16;
        margin: 1 0;
    }
    .modal-buttons {
        align-horizontal: center;
        height: 3;
    }
    """

    def on_mount(self) -> None:
        list_view = self.query_one("#merge-list", ListView)
        for cand in self._candidates:
            cid = cand.get("id", 0)
            if cid == self._current_id:
                continue
            name = cand.get("name", cand.get("narrative", f"#{cid}"))
            status = cand.get("status", "")
            list_view.append(ListItem(Static(f"#{cid}  {name}  [{status}]")))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        label = event.item.query_one(Static).renderable
        # Parse target id from the label format "#ID  name  [status]"
        try:
            target_id = int(str(label).split()[0].lstrip("#"))
        except (ValueError, IndexError):
            return
        self.dismiss(target_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class SplitModal(ModalScreen[Optional[list[int]]]):
    """Modal for splitting an interpretation.

    Shows a list of constituent themes. The user selects which themes
    should go into the first new interpretation; remaining themes form
    the second. Returns list of theme ids for the first group, or None.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("space", "toggle_selection", "Toggle", show=False),
    ]

    def __init__(
        self,
        themes: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self._themes = themes
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Split Interpretation[/bold]\n"
            "Select themes for the FIRST new interpretation "
            "(space to toggle):",
            id="split-title",
        )
        yield ListView(id="split-list")
        with Horizontal(classes="modal-buttons"):
            yield Button("Split", variant="primary", id="split-execute")
            yield Button("Cancel", variant="default", id="split-cancel")

    CSS = """
    SplitModal {
        align: center middle;
    }
    SplitModal > Vertical, SplitModal > Static, SplitModal > ListView,
    SplitModal > Horizontal {
        width: 60;
    }
    #split-title {
        text-align: center;
        padding: 1 0;
    }
    #split-list {
        height: 16;
        margin: 1 0;
    }
    .modal-buttons {
        align-horizontal: center;
        height: 3;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    def on_mount(self) -> None:
        list_view = self.query_one("#split-list", ListView)
        for theme in self._themes:
            tid = theme.get("id", 0)
            name = theme.get("name", f"#{tid}")
            tag = theme.get("tag", "")
            list_view.append(
                ListItem(
                    Static(f"  #{tid}  {name}  [{tag}]"),
                    id=f"theme-{tid}",
                )
            )

    def action_toggle_selection(self) -> None:
        list_view = self.query_one("#split-list", ListView)
        idx = list_view.index
        if idx is None or idx >= len(self._themes):
            return
        theme = self._themes[idx]
        tid = theme.get("id", 0)
        if tid in self._selected:
            self._selected.discard(tid)
            self._update_item_mark(idx, " ")
        else:
            self._selected.add(tid)
            self._update_item_mark(idx, ">")

    def _update_item_mark(self, index: int, mark: str) -> None:
        list_view = self.query_one("#split-list", ListView)
        children = list(list_view.children)
        if 0 <= index < len(children):
            item = children[index]
            static = item.query_one(Static)
            # Extract text after the mark character
            text = str(static.renderable)
            # Strip existing mark
            clean = text[1:] if text and text[0] in " >" else text
            static.update(f"{mark}{clean}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Treat selection as toggle (same as space)
        self.action_toggle_selection()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "split-execute":
            if not self._selected:
                self.dismiss(None)
                return
            self.dismiss(list(self._selected))
        else:
            self.dismiss(None)
