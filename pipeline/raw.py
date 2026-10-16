"""The raw layer: one tidy table per source and download day, in data/raw/<source>/<date>.parquet."""

from datetime import date
from pathlib import Path

import pandas as pd

from pipeline import files
from pipeline.catalog import Series, main_field

COLUMNS = ["date", "instrument", "field", "value", "source", "downloaded_at"]


def write(table: pd.DataFrame, raw_dir: Path, source: str, download_date: date) -> Path:
    """Write a source's table for the day; a second run on the same day replaces the file."""
    return files.write_parquet(table, raw_dir / source / f"{download_date:%Y-%m-%d}.parquet")


def read_latest(raw_dir: Path, source: str) -> tuple[pd.DataFrame | None, Path | None]:
    files_found = sorted((raw_dir / source).glob("*.parquet"))  # names are dates, so the last is the newest
    if not files_found:
        return None, None
    return pd.read_parquet(files_found[-1]), files_found[-1]


def series_values(raw: pd.DataFrame, series: Series) -> pd.Series:
    """The series' main field indexed by date; duplicates keep the last row (the quality gate reports them)."""
    rows = raw[(raw["instrument"] == series.instrument) & (raw["field"] == main_field(series))]
    rows = rows.drop_duplicates("date", keep="last")
    return rows.set_index("date")["value"].sort_index()


def series_fields(raw: pd.DataFrame, series: Series, fields: list[str]) -> pd.DataFrame:
    """Several fields of one series, one column each, indexed by date; duplicates keep the last row."""
    rows = raw[(raw["instrument"] == series.instrument) & raw["field"].isin(fields)]
    rows = rows.drop_duplicates(["date", "field"], keep="last")
    return rows.pivot(index="date", columns="field", values="value").reindex(columns=fields).sort_index()
