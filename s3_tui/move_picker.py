from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from s3_tui.s3_service import S3Entry, S3Service


@dataclass(slots=True)
class MoveTarget:
    bucket: str
    prefix: str


class MovePickerTable(DataTable):
    BINDINGS = [
        Binding("enter", "open_selected", show=False, priority=True),
        Binding("backspace", "go_parent", show=False, priority=True),
    ]

    def action_open_selected(self) -> None:
        callback = getattr(self.screen, "action_open_selected_entry", None)
        if callable(callback):
            callback()

    def action_go_parent(self) -> None:
        callback = getattr(self.screen, "action_go_parent", None)
        if callable(callback):
            callback()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_open_selected()
            event.stop()
        elif event.key in {"backspace", "ctrl+h"}:
            self.action_go_parent()
            event.stop()


class MovePickerScreen(ModalScreen[MoveTarget | None]):
    DEFAULT_CSS = """
    MovePickerScreen {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("enter", "open_selected_entry", "Open"),
        Binding("backspace", "go_parent", "Parent"),
        Binding("m", "confirm_target", "Move Here"),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("left", "cursor_left", show=False, priority=True),
        Binding("right", "cursor_right", show=False, priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, service: S3Service, source_label: str) -> None:
        super().__init__()
        self.service = service
        self.source_label = source_label
        self.mode = "buckets"
        self.bucket: str | None = None
        self.prefix = ""
        self.entries: list[S3Entry] = []
        self.status_message = ""

    def compose(self) -> ComposeResult:
        with Container(id="move_modal"):
            yield Static("Move target", id="move_modal_title")
            yield Static(self.source_label, id="move_modal_source")
            yield Static("", id="move_modal_path")
            yield Static("", id="move_modal_status")
            yield MovePickerTable(id="move_table", cursor_type="cell")
            with Horizontal(id="move_modal_actions"):
                yield Button("Move here", id="move_here_btn", classes="flat-button confirm-create")
                yield Button("Cancel", id="move_cancel_btn", classes="flat-button confirm-neutral")

    def on_mount(self) -> None:
        table = self.query_one("#move_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Type")
        self._refresh_entries()
        table.focus()

    def _refresh_entries(self) -> None:
        if self.mode == "buckets":
            self.entries = self.service.list_buckets()
            self.status_message = "Enter: abrir bucket | M: mover para o local atual"
            current_path = "s3://"
        else:
            self.entries = self.service.list_prefix(self.bucket or "", self.prefix)
            self.status_message = "Enter: abrir pasta | Backspace: subir | M: mover para o local atual"
            current_path = f"s3://{self.bucket}/{self.prefix}"

        table = self.query_one("#move_table", DataTable)
        table.clear()
        for entry in self.entries:
            kind = {"bucket": "bucket", "parent": "..", "dir": "dir", "file": "file"}[entry.kind]
            table.add_row(entry.name, kind)

        self.query_one("#move_modal_path", Static).update(current_path)
        self.query_one("#move_modal_status", Static).update(self.status_message)
        if self.entries:
            try:
                table.move_cursor(row=0, column=0)
            except Exception:
                pass

    def _selected_entry(self) -> S3Entry | None:
        if not self.entries:
            return None
        table = self.query_one("#move_table", DataTable)
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(self.entries):
            return None
        return self.entries[row_index]

    def action_open_selected_entry(self) -> None:
        selected = self._selected_entry()
        if selected is None:
            return
        if self.mode == "buckets" and selected.kind == "bucket":
            self.mode = "objects"
            self.bucket = selected.name
            self.prefix = ""
            self._refresh_entries()
            return
        if self.mode != "objects":
            return
        if selected.kind == "parent":
            self.action_go_parent()
        elif selected.kind == "dir":
            self.prefix = selected.key
            self._refresh_entries()

    def action_go_parent(self) -> None:
        if self.mode == "buckets":
            return
        if not self.prefix:
            self.mode = "buckets"
            self.bucket = None
            self._refresh_entries()
            return
        parts = self.prefix.rstrip("/").split("/")
        parent_parts = parts[:-1]
        self.prefix = ("/".join(parent_parts) + "/") if parent_parts else ""
        self._refresh_entries()

    def action_confirm_target(self) -> None:
        if self.mode != "objects" or self.bucket is None:
            self.query_one("#move_modal_status", Static).update("Selecione um bucket primeiro.")
            return
        self.dismiss(MoveTarget(bucket=self.bucket, prefix=self.prefix))

    def action_cursor_up(self) -> None:
        self._move_cursor("up")

    def action_cursor_down(self) -> None:
        self._move_cursor("down")

    def action_cursor_left(self) -> None:
        self._move_cursor("left")

    def action_cursor_right(self) -> None:
        self._move_cursor("right")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "move_here_btn":
            self.action_confirm_target()
        elif event.button.id == "move_cancel_btn":
            self.action_cancel()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_open_selected_entry()
            event.stop()
        elif event.key in {"backspace", "ctrl+h"}:
            self.action_go_parent()
            event.stop()
        elif event.key in {"up", "down", "left", "right"}:
            self._move_cursor(event.key)
            event.stop()

    def _move_cursor(self, direction: str) -> None:
        table = self.query_one("#move_table", DataTable)
        action = getattr(table, f"action_cursor_{direction}", None)
        if callable(action):
            action()
        table.focus()
