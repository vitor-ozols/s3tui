from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.events import Click, Key
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from s3_tui.models import LocalFsEntry


class UploadFsTable(DataTable):
    """DataTable que sobrescreve action_select_cursor para controlar o Enter."""

    BINDINGS = [
        Binding("enter", "select_cursor", show=False, priority=True),
        Binding("u", "upload_selected", show=False, priority=True),
        Binding("backspace", "go_parent", show=False, priority=True),
    ]

    def action_select_cursor(self) -> None:
        callback = getattr(self.screen, "action_open_or_select", None)
        if callable(callback):
            callback()

    def action_upload_selected(self) -> None:
        callback = getattr(self.screen, "action_upload_selected", None)
        if callable(callback):
            callback()

    def action_go_parent(self) -> None:
        callback = getattr(self.screen, "action_go_parent", None)
        if callable(callback):
            callback()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_select_cursor()
            event.stop()
        elif event.key in {"backspace", "ctrl+h"}:
            self.action_go_parent()
            event.stop()
        elif event.key == "u":
            self.action_upload_selected()
            event.stop()


class UploadPickerScreen(ModalScreen[Path | None]):
    BINDINGS = [
        Binding("enter", "open_or_select", "Open"),
        Binding("backspace", "go_parent", "Parent"),
        Binding("u", "upload_selected", "Upload"),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("left", "cursor_left", show=False, priority=True),
        Binding("right", "cursor_right", show=False, priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start_dir: Path | None = None) -> None:
        super().__init__()
        self.current_dir = (start_dir or Path.home()).expanduser().resolve()
        self.entries: list[LocalFsEntry] = []
        self.status_message = ""
        self._last_mouse_click_row: int | None = None
        self._last_mouse_click_ts: float = 0.0

    def compose(self) -> ComposeResult:
        with Container(id="upload_modal"):
            yield Static("Upload (file or folder)", id="upload_modal_title")
            yield Static("", id="upload_current_path")
            yield Static("", id="upload_status")
            yield UploadFsTable(id="upload_fs_table", cursor_type="cell")
            with Horizontal(id="upload_modal_actions"):
                yield Button("Upload selected", id="upload_select_btn", classes="flat-button")
                yield Button("Cancel", id="upload_cancel_btn", classes="flat-button")

    def on_mount(self) -> None:
        table = self.query_one("#upload_fs_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Size", "Modified")
        self._refresh_entries()
        table.focus()

    def _refresh_entries(self) -> None:
        table = self.query_one("#upload_fs_table", DataTable)
        entries: list[LocalFsEntry] = []
        self.status_message = "Enter: abrir pasta | U: fazer upload | Backspace: pasta pai"
        parent = self.current_dir.parent
        if parent != self.current_dir:
            entries.append(LocalFsEntry(path=parent, name="..", kind="parent"))

        try:
            dirs: list[LocalFsEntry] = []
            files: list[LocalFsEntry] = []
            for child in self.current_dir.iterdir():
                try:
                    stat = child.stat()
                except OSError:
                    continue
                modified = datetime.fromtimestamp(stat.st_mtime)
                if child.is_dir():
                    dirs.append(LocalFsEntry(path=child, name=child.name, kind="dir", modified=modified))
                else:
                    files.append(
                        LocalFsEntry(
                            path=child,
                            name=child.name,
                            kind="file",
                            size=int(stat.st_size),
                            modified=modified,
                        )
                    )
            dirs.sort(key=lambda item: item.name.lower())
            files.sort(key=lambda item: item.name.lower())
            entries.extend(dirs)
            entries.extend(files)
        except OSError as error:
            self.status_message = f"Filesystem error: {error}"

        self.entries = entries
        table.clear()
        for entry in self.entries:
            size = "" if entry.kind != "file" else self._human_size(entry.size)
            modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else ""
            table.add_row(entry.name, entry.kind, size, modified)

        self.query_one("#upload_current_path", Static).update(str(self.current_dir))
        self.query_one("#upload_status", Static).update(self.status_message)
        if self.entries:
            try:
                table.move_cursor(row=0, column=0)
            except Exception:
                pass

    def _selected_entry(self) -> LocalFsEntry | None:
        table = self.query_one("#upload_fs_table", DataTable)
        if not self.entries:
            return None
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(self.entries):
            return None
        return self.entries[row_index]

    def action_open_or_select(self) -> None:
        selected = self._selected_entry()
        if selected is None:
            return
        if selected.kind in {"dir", "parent"}:
            try:
                self.current_dir = selected.path.resolve()
                self._refresh_entries()
            except OSError as error:
                self.status_message = f"Cannot open folder: {error}"
                self.query_one("#upload_status", Static).update(self.status_message)
            return
        self.status_message = "Press U to upload selected file."
        self.query_one("#upload_status", Static).update(self.status_message)

    def action_go_parent(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            try:
                self.current_dir = parent.resolve()
                self._refresh_entries()
            except OSError as error:
                self.status_message = f"Cannot open parent: {error}"
                self.query_one("#upload_status", Static).update(self.status_message)

    def action_upload_selected(self) -> None:
        selected = self._selected_entry()
        if selected is None:
            return
        if selected.kind == "parent":
            self.action_go_parent()
            return
        self.dismiss(selected.path)

    def action_cursor_up(self) -> None:
        self._move_upload_cursor("up")

    def action_cursor_down(self) -> None:
        self._move_upload_cursor("down")

    def action_cursor_left(self) -> None:
        self._move_upload_cursor("left")

    def action_cursor_right(self) -> None:
        self._move_upload_cursor("right")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id != "upload_fs_table":
            return
        now = monotonic()
        row = event.coordinate.row
        is_double_click = self._last_mouse_click_row == row and (now - self._last_mouse_click_ts) <= 0.45
        self._last_mouse_click_row = None
        self._last_mouse_click_ts = 0.0
        if is_double_click:
            selected = self._selected_entry()
            if selected and selected.kind in {"dir", "parent"}:
                self.action_open_or_select()

    def on_click(self, event: Click) -> None:
        if event.widget and event.widget.id == "upload_fs_table":
            table = self.query_one("#upload_fs_table", DataTable)
            self._last_mouse_click_row = table.cursor_coordinate.row
            self._last_mouse_click_ts = monotonic()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload_select_btn":
            self.action_upload_selected()
        elif event.button.id == "upload_cancel_btn":
            self.action_cancel()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_open_or_select()
            event.stop()
        elif event.key == "backspace":
            self.action_go_parent()
            event.stop()
        elif event.key in {"up", "down", "left", "right"}:
            self._move_upload_cursor(event.key)
            event.stop()

    @staticmethod
    def _human_size(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _move_upload_cursor(self, direction: str) -> None:
        table = self.query_one("#upload_fs_table", DataTable)
        action = getattr(table, f"action_cursor_{direction}", None)
        if callable(action):
            action()
        table.focus()
