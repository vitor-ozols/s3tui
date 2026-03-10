from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from s3_tui.s3_service import S3Entry


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


@dataclass(slots=True)
class LocalFsEntry:
    path: Path
    name: str
    kind: str
    size: int = 0
    modified: datetime | None = None
