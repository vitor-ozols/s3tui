from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".log",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".sql",
    ".py",
    ".sh",
    ".js",
    ".ts",
    ".html",
    ".css",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".tif",
}


def is_image_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _df_preview(df: pd.DataFrame, max_rows: int = 500) -> str:
    shown = df.head(max_rows)
    return shown.to_string(index=False, max_rows=max_rows)


def _df_to_table(df: pd.DataFrame, max_rows: int = 500) -> tuple[list[str], list[list[str]]]:
    shown = df.head(max_rows)
    columns = [str(col) for col in shown.columns]
    rows = [
        ["" if pd.isna(value) else str(value) for value in row]
        for row in shown.itertuples(index=False, name=None)
    ]
    return columns, rows


def build_table_preview(
    filename: str, content: bytes, max_rows: int = 500
) -> tuple[list[str], list[list[str]]] | None:
    ext = Path(filename).suffix.lower()

    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(content), nrows=max_rows)
        return _df_to_table(df, max_rows=max_rows)

    if ext in {".json", ".jsonl", ".ndjson"}:
        if ext in {".jsonl", ".ndjson"}:
            lines = content.decode("utf-8", errors="replace").splitlines()[:max_rows]
            records = [json.loads(line) for line in lines if line.strip()]
            if not records:
                return None
            df = pd.json_normalize(records)
            return _df_to_table(df, max_rows=max_rows)

        parsed = json.loads(content.decode("utf-8", errors="replace"))
        if isinstance(parsed, list):
            df = pd.json_normalize(parsed[:max_rows])
            return _df_to_table(df, max_rows=max_rows)
        if isinstance(parsed, dict):
            df = pd.json_normalize(parsed)
            return _df_to_table(df, max_rows=max_rows)
        return None

    if ext == ".parquet":
        df = pd.read_parquet(io.BytesIO(content))
        return _df_to_table(df, max_rows=max_rows)

    return None


def build_preview(filename: str, content: bytes, max_rows: int = 500) -> str:
    ext = Path(filename).suffix.lower()

    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(content), nrows=max_rows)
        return _df_preview(df, max_rows=max_rows)

    if ext in {".json", ".jsonl", ".ndjson"}:
        if ext in {".jsonl", ".ndjson"}:
            lines = content.decode("utf-8", errors="replace").splitlines()[:max_rows]
            records = [json.loads(line) for line in lines if line.strip()]
            df = pd.json_normalize(records)
            return _df_preview(df, max_rows=max_rows)

        parsed = json.loads(content.decode("utf-8", errors="replace"))
        if isinstance(parsed, list):
            df = pd.json_normalize(parsed[:max_rows])
            return _df_preview(df, max_rows=max_rows)
        if isinstance(parsed, dict):
            df = pd.json_normalize(parsed)
            return _df_preview(df, max_rows=max_rows)
        return str(parsed)

    if ext == ".parquet":
        df = pd.read_parquet(io.BytesIO(content))
        return _df_preview(df, max_rows=max_rows)

    if not ext or ext in TEXT_EXTENSIONS:
        text = content.decode("utf-8", errors="replace")
        return text[:12000]

    return "Preview is not supported for this file type."
