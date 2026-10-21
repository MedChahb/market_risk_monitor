"""Atomic Parquet writes: a crash never leaves a half-written file behind."""

from pathlib import Path

import pandas as pd


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    return path
