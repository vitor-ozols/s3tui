from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError


EntryType = Literal["bucket", "parent", "dir", "file"]


@dataclass(slots=True)
class S3Entry:
    name: str
    key: str
    kind: EntryType
    size: int = 0
    modified: datetime | None = None


class S3Service:
    def __init__(self, profile: str | None = None, region: str | None = None) -> None:
        session = boto3.Session(profile_name=profile, region_name=region)
        self.client = session.client("s3")

    def list_buckets(self) -> list[S3Entry]:
        response = self.client.list_buckets()
        buckets = response.get("Buckets", [])
        entries = [
            S3Entry(
                name=b["Name"],
                key=b["Name"],
                kind="bucket",
                modified=b.get("CreationDate"),
            )
            for b in buckets
        ]
        return sorted(entries, key=lambda e: e.name.lower())

    def list_prefix(self, bucket: str, prefix: str = "") -> list[S3Entry]:
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/")

        entries: list[S3Entry] = []
        if prefix:
            entries.append(S3Entry(name="..", key="..", kind="parent"))

        for page in pages:
            for cp in page.get("CommonPrefixes", []):
                sub_prefix = cp["Prefix"]
                name = sub_prefix[len(prefix) :].rstrip("/")
                entries.append(S3Entry(name=name, key=sub_prefix, kind="dir"))

            for obj in page.get("Contents", []):
                if obj["Key"] == prefix:
                    continue
                name = obj["Key"][len(prefix) :]
                if "/" in name:
                    continue
                entries.append(
                    S3Entry(
                        name=name,
                        key=obj["Key"],
                        kind="file",
                        size=int(obj.get("Size", 0)),
                        modified=obj.get("LastModified"),
                    )
                )

        dirs = sorted((e for e in entries if e.kind == "dir"), key=lambda e: e.name.lower())
        files = sorted((e for e in entries if e.kind == "file"), key=lambda e: e.name.lower())
        parent = [e for e in entries if e.kind == "parent"]
        return parent + dirs + files

    def read_object(self, bucket: str, key: str, max_bytes: int | None = None) -> bytes:
        kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
        if max_bytes is not None:
            kwargs["Range"] = f"bytes=0-{max_bytes - 1}"
        response = self.client.get_object(**kwargs)
        return response["Body"].read()

    def download(self, bucket: str, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(bucket, key, str(destination))

    def upload_file(self, bucket: str, key: str, source: Path) -> None:
        self.client.upload_file(str(source), bucket, key)

    def upload_directory(self, bucket: str, source_dir: Path, prefix: str = "") -> int:
        uploaded = 0
        base_prefix = prefix.rstrip("/")
        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(source_dir).as_posix()
            key = f"{base_prefix}/{relative}" if base_prefix else relative
            self.upload_file(bucket, key, file_path)
            uploaded += 1
        return uploaded

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        source = {"Bucket": src_bucket, "Key": src_key}
        self.client.copy_object(Bucket=dst_bucket, Key=dst_key, CopySource=source)

    def move(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        self.copy(src_bucket, src_key, dst_bucket, dst_key)
        self.delete(src_bucket, src_key)

    def delete(self, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)


class S3ServiceError(RuntimeError):
    @classmethod
    def from_exception(cls, error: Exception) -> "S3ServiceError":
        if isinstance(error, (BotoCoreError, ClientError)):
            return cls(str(error))
        return cls(f"Unexpected S3 error: {error}")
