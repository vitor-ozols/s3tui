from __future__ import annotations

from pathlib import Path
from time import monotonic

from botocore.exceptions import BotoCoreError, ClientError
from textual.css.query import NoMatches
from textual.events import Key
from textual.widgets import DataTable, Input

from s3_tui.s3_service import S3Entry
from s3_tui.upload_picker import UploadPickerScreen


class ExplorerMixin:
    def _table(self) -> DataTable:
        return self.query_one("#left_table", DataTable)

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

    def _selected_entry(self) -> S3Entry | None:
        try:
            table = self._table()
        except NoMatches:
            return None
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

    def action_open_selected(self) -> None:
        if isinstance(self.screen, UploadPickerScreen):
            self.screen.action_open_or_select()
            return
        entry = self._selected_entry()
        if entry:
            self._open_entry(entry)

    def action_go_up(self) -> None:
        if isinstance(self.screen, UploadPickerScreen):
            self.screen.action_go_parent()
            return
        self._go_up()

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

    def action_upload_selected(self) -> None:
        if isinstance(self.screen, UploadPickerScreen):
            self.screen.action_upload_selected()
            return
        if self.left.mode != "objects" or self.left.bucket is None:
            self._log("Upload unavailable: select a bucket/path in pane 1 first.")
            return

        self.push_screen(UploadPickerScreen(Path.home()), self._on_upload_picked)

    def _on_upload_picked(self, selected_path: Path | None) -> None:
        if selected_path is None:
            return
        if self.left.mode != "objects" or self.left.bucket is None:
            self._log("Upload aborted: no destination bucket selected.")
            return

        destination_prefix = self.left.prefix or ""
        bucket = self.left.bucket
        try:
            if selected_path.is_file():
                key = f"{destination_prefix}{selected_path.name}"
                self.service.upload_file(bucket, key, selected_path)
                self._log(f"Uploaded file: {selected_path} -> s3://{bucket}/{key}")
            elif selected_path.is_dir():
                target_prefix = f"{destination_prefix}{selected_path.name}"
                uploaded_count = self.service.upload_directory(bucket, selected_path, prefix=target_prefix)
                self._log(
                    f"Uploaded folder: {selected_path} -> s3://{bucket}/{target_prefix}/ "
                    f"({uploaded_count} files)"
                )
            else:
                self._log(f"Upload failed: invalid path {selected_path}")
                return
            self._refresh_left()
        except Exception as error:
            self._log(f"Upload failed: {error}")

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
        if isinstance(self.screen, UploadPickerScreen):
            return
        if event.key == "enter":
            self.action_open_selected()
