"""Builders of small synthetic tables shared by the tests."""

import numpy as np
import pandas as pd

from pipeline import raw
from pipeline.catalog import get, main_field

STAMP = pd.Timestamp("2026-10-21 18:00", tz="UTC")


def raw_table(instrument: str, dates: pd.DatetimeIndex, values=None) -> pd.DataFrame:
    """A raw-layer table for one catalog series; values default to a smooth rise from 100 to 110."""
    series = get(instrument)
    values = np.linspace(100, 110, len(dates)) if values is None else np.asarray(values, dtype=float)
    table = pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
            "instrument": instrument,
            "field": main_field(series),
            "value": values,
            "source": series.source,
            "downloaded_at": STAMP,
        }
    )
    return table[raw.COLUMNS]
