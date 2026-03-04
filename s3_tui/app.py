from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from botocore.exceptions import BotoCoreError, ClientError
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Key, MouseScrollDown, MouseScrollUp
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static

from s3_tui.preview import build_preview, build_table_preview
from s3_tui.s3_service import S3Entry, S3Service


@dataclass(slots=True)
class PaneState:
    table_id: str
    path_id: str
    mode: str = "buckets"
    bucket: str | None = None
    prefix: str = ""
    entries: list[S3Entry] = field(default_factory=list)
    all_entries: list[S3Entry] = field(default_factory=list)

    @property
    def path(self) -> str:
        if self.mode == "buckets":
            return "s3://"
        return f"s3://{self.bucket}/{self.prefix}"


class S3TUI(App[None]):
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    TITLE = "S3 Commander"
    SUB_TITLE = "Explorer + details"

    BINDINGS = [
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("backspace", "go_up", "Up"),
        Binding("p", "preview_selected", "Preview"),
        Binding("pagedown", "preview_page_down", "Preview Down"),
        Binding("pageup", "preview_page_up", "Preview Up"),
        Binding("shift+left", "preview_scroll_left", "Preview Left"),
        Binding("shift+right", "preview_scroll_right", "Preview Right"),
        Binding("d", "download_selected", "Download"),
        Binding("c", "copy_selected", "Copy"),
        Binding("m", "move_selected", "Move"),
        Binding("delete", "delete_selected", "Delete"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, profile: str | None = None, region: str | None = None) -> None:
        super().__init__()
        self.service = S3Service(profile=profile, region=region)
        self.left = PaneState(table_id="left_table", path_id="left_path")
        self.search_query = ""
        self._last_click_row: int | None = None
        self._last_click_ts = 0.0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            with Horizontal(id="panes"):
                with Container(classes="pane"):
                    yield Static("s3://", id="left_path", classes="pane_path")
                    yield Input(placeholder="Search (real-time autocomplete)", id="search_input")
                    yield Static("", id="search_hint", classes="search_hint")
                    yield DataTable(id="left_table", cursor_type="cell")
                with Container(classes="pane"):
                    yield Static("Selected item details", id="right_path", classes="pane_path")
                    yield Static("No item selected.", id="right_info", classes="info_panel")
            with Container(id="preview_wrap"):
                yield Static("Preview", id="preview_title")
                yield DataTable(id="preview_table", cursor_type="cell")
                yield RichLog(id="preview", wrap=False, markup=False, auto_scroll=False)
        yield Footer()

    def on_mount(self) -> None:
        self.dark = True
        self._init_table(self._table())
        preview_table = self._preview_table()
        if hasattr(preview_table, "show_cursor"):
            preview_table.show_cursor = True
        if hasattr(preview_table, "zebra_stripes"):
            preview_table.zebra_stripes = True
        self._show_log_preview()
        self._refresh_left()
        self._table().focus()
        self._update_right_info(self._selected_entry())
        self._log("Type in the search box to filter and autocomplete in real time.")

    def _table(self) -> DataTable:
        return self.query_one("#left_table", DataTable)

    def _path_widget(self) -> Static:
        return self.query_one(f"#{self.left.path_id}", Static)

    def _right_info(self) -> Static:
        return self.query_one("#right_info", Static)

    def _search_hint(self) -> Static:
        return self.query_one("#search_hint", Static)

    def _preview(self) -> RichLog:
        return self.query_one("#preview", RichLog)

    def _preview_table(self) -> DataTable:
        return self.query_one("#preview_table", DataTable)

    def _clear_search(self) -> None:
        self.search_query = ""
        self._search_hint().update("")
        search_input = self.query_one("#search_input", Input)
        if search_input.value:
            search_input.value = ""

    def _init_table(self, table: DataTable) -> None:
        if hasattr(table, "cursor_type"):
            table.cursor_type = "cell"
        if hasattr(table, "show_cursor"):
            table.show_cursor = True
        if hasattr(table, "zebra_stripes"):
            table.zebra_stripes = True
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Size", "Modified")

    def _log(self, message: str) -> None:
        self._preview().write(message)

    def _show_log_preview(self) -> None:
        self._preview_table().display = False
        self._preview().display = True

    def _show_table_preview(self) -> None:
        self._preview().display = False
        self._preview_table().display = True

    def _preview_widget(self) -> DataTable | RichLog:
        table = self._preview_table()
        return table if table.display else self._preview()

    def _scroll_preview_horizontal(self, delta: int) -> None:
        widget = self._preview_widget()
        widget.scroll_to(x=widget.scroll_x + delta, y=widget.scroll_y, animate=False)

    def _selected_entry(self) -> S3Entry | None:
        table = self._table()
        if not self.left.entries:
            return None
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(self.left.entries):
            return None
        return self.left.entries[row_index]

    def _render_entries(self) -> None:
        table = self._table()
        table.clear()
        for entry in self.left.entries:
            kind = {
                "bucket": "bucket",
                "parent": "..",
                "dir": "dir",
                "file": "file",
            }[entry.kind]
            size = "" if entry.kind != "file" else self._human_size(entry.size)
            modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else ""
            table.add_row(entry.name, kind, size, modified)

        self._path_widget().update(self.left.path)
        self._select_first_row()
        self._update_search_hint()
        self._update_right_info(self._selected_entry())

    def _select_first_row(self) -> None:
        if not self.left.entries:
            return
        table = self._table()
        try:
            table.move_cursor(row=0, column=0)
        except Exception:
            pass

    def _apply_filter(self) -> None:
        query = self.search_query.strip().lower()
        if not query:
            self.left.entries = list(self.left.all_entries)
            self._render_entries()
            return

        filtered: list[S3Entry] = []
        for entry in self.left.all_entries:
            if entry.kind == "parent":
                filtered.append(entry)
                continue
            if query in entry.name.lower():
                filtered.append(entry)

        self.left.entries = filtered
        self._render_entries()

    def _update_search_hint(self) -> None:
        query = self.search_query.strip().lower()
        if not query:
            self._search_hint().update("")
            return

        for entry in self.left.all_entries:
            if entry.kind == "parent":
                continue
            if entry.name.lower().startswith(query):
                self._search_hint().update(f"Autocomplete: {entry.name}")
                return
            if query in entry.name.lower():
                self._search_hint().update(f"Match: {entry.name}")
                return

        self._search_hint().update("No results")

    @staticmethod
    def _human_size(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _refresh_left(self) -> None:
        try:
            if self.left.mode == "buckets":
                self.left.all_entries = self.service.list_buckets()
            else:
                self.left.all_entries = self.service.list_prefix(bucket=self.left.bucket or "", prefix=self.left.prefix)
            self._apply_filter()
        except (BotoCoreError, ClientError) as error:
            self._log(f"S3 error: {error}")

    def _entry_uri(self, entry: S3Entry) -> str:
        if entry.kind == "bucket":
            return f"s3://{entry.name}/"
        if self.left.bucket is None:
            return entry.name
        if entry.kind == "parent":
            return f"s3://{self.left.bucket}/{self.left.prefix}.."
        return f"s3://{self.left.bucket}/{entry.key}"

    def _update_right_info(self, entry: S3Entry | None) -> None:
        if entry is None:
            self._right_info().update("No item selected.")
            return

        modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else "-"
        size = self._human_size(entry.size) if entry.kind == "file" else "-"
        details = (
            f"Name: {entry.name}\n"
            f"Type: {entry.kind}\n"
            f"URI: {self._entry_uri(entry)}\n"
            f"Size: {size}\n"
            f"Modified: {modified}\n"
            f"Context: {self.left.path}"
        )
        self._right_info().update(details)

    def _open_entry(self, entry: S3Entry) -> None:
        if self.left.mode == "buckets" and entry.kind == "bucket":
            self._clear_search()
            self.left.mode = "objects"
            self.left.bucket = entry.name
            self.left.prefix = ""
            self._refresh_left()
            return

        if self.left.mode != "objects":
            return

        if entry.kind == "parent":
            self._go_up()
            return

        if entry.kind == "dir":
            self._clear_search()
            self.left.prefix = entry.key
            self._refresh_left()
            return

        if entry.kind == "file":
            self._preview_file(entry)

    def _go_up(self) -> None:
        if self.left.mode == "buckets":
            return

        self._clear_search()
        if not self.left.prefix:
            self.left.mode = "buckets"
            self.left.bucket = None
            self.left.prefix = ""
            self._refresh_left()
            return

        parts = self.left.prefix.rstrip("/").split("/")
        parent_parts = parts[:-1]
        self.left.prefix = ("/".join(parent_parts) + "/") if parent_parts else ""
        self._refresh_left()

    def _preview_file(self, entry: S3Entry) -> None:
        if self.left.bucket is None or entry.kind != "file":
            return

        if entry.size > 25 * 1024 * 1024:
            self._log(f"Preview blocked: large file ({self._human_size(entry.size)}).")
            return

        try:
            content = self.service.read_object(self.left.bucket, entry.key)
            table_preview = build_table_preview(entry.name, content)
            if table_preview is not None:
                columns, rows = table_preview
                table = self._preview_table()
                table.clear(columns=True)
                if not columns:
                    columns = ["value"]
                table.add_columns(*columns)
                for row in rows:
                    table.add_row(*row)
                if hasattr(table, "show_cursor"):
                    table.show_cursor = True
                if hasattr(table, "zebra_stripes"):
                    table.zebra_stripes = True
                self._show_table_preview()
                table.move_cursor(row=0, column=0)
            else:
                text = build_preview(entry.name, content)
                self._preview().clear()
                self._show_log_preview()
                self._log(f"Preview: s3://{self.left.bucket}/{entry.key}")
                self._log(text)
        except Exception as error:
            self._show_log_preview()
            self._log(f"Preview failed: {error}")

    def action_open_selected(self) -> None:
        entry = self._selected_entry()
        if entry:
            self._open_entry(entry)

    def action_go_up(self) -> None:
        self._go_up()

    def action_preview_selected(self) -> None:
        entry = self._selected_entry()
        if entry and entry.kind == "file":
            self._preview_file(entry)

    def action_preview_page_down(self) -> None:
        self._preview_widget().scroll_page_down(animate=False)

    def action_preview_page_up(self) -> None:
        self._preview_widget().scroll_page_up(animate=False)

    def action_preview_scroll_left(self) -> None:
        self._scroll_preview_horizontal(-8)

    def action_preview_scroll_right(self) -> None:
        self._scroll_preview_horizontal(8)

    def action_refresh(self) -> None:
        self._refresh_left()

    def action_download_selected(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.kind != "file" or self.left.bucket is None:
            return

        destination = Path("downloads") / self.left.bucket / entry.key
        try:
            self.service.download(self.left.bucket, entry.key, destination)
            self._log(f"Download: s3://{self.left.bucket}/{entry.key} -> {destination}")
        except Exception as error:
            self._log(f"Download failed: {error}")

    def action_copy_selected(self) -> None:
        self._log("Copy is disabled in this layout (right panel = details).")

    def action_move_selected(self) -> None:
        self._log("Move is disabled in this layout (right panel = details).")

    def action_delete_selected(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.kind != "file" or self.left.bucket is None:
            return

        try:
            self.service.delete(self.left.bucket, entry.key)
            self._refresh_left()
            self._log(f"Deleted: s3://{self.left.bucket}/{entry.key}")
        except Exception as error:
            self._log(f"Delete failed: {error}")

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        row = event.coordinate.row
        if event.data_table.id == self.left.table_id and 0 <= row < len(self.left.entries):
            self._update_right_info(self.left.entries[row])

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        row = event.coordinate.row
        if event.data_table.id == self.left.table_id and 0 <= row < len(self.left.entries):
            entry = self.left.entries[row]
            self._update_right_info(entry)
            now = monotonic()
            is_double_click = self._last_click_row == row and (now - self._last_click_ts) <= 0.45
            self._last_click_row = row
            self._last_click_ts = now
            if is_double_click:
                self._open_entry(entry)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input":
            self.search_query = event.value
            self._apply_filter()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_open_selected()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if event.shift:
            self._scroll_preview_horizontal(-4)
            event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if event.shift:
            self._scroll_preview_horizontal(4)
            event.stop()


def main() -> None:
    S3TUI().run()


if __name__ == "__main__":
    main()
