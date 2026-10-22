"""Detector of suspect prices in the daily closes of the Yahoo price series.

A day is suspect when its log return is extreme for that series (robust z-score against the previous 63
returns) and either comes straight back the next day while the other assets stayed quiet (a bad tick),
or is larger than any real move (a level shift, such as an unadjusted split). A real crash stays and is
shared by the market; a data error comes back or hits one asset. The quality gate reports these days
as a warning rule; `anomaly_evaluation.py` measures the detector on injected errors.
"""

import numpy as np
import pandas as pd

from pipeline import raw
from pipeline.catalog import CATALOG

Z_WINDOW = 63  # past returns in the robust median and MAD; adapts within a quarter after a regime change
MAD_SCALE = 1.4826  # makes the MAD a standard deviation for normal returns (Rousseeuw and Croux, 1993)
REVERSAL_Z = 6.0  # robust z of a bad tick
REVERSAL_SHARE = 1 / 3  # at most this share of the move remains after the next day
MARKET_Z = 3.0  # the other assets' median robust z stays inside this band: the move is not shared
LEVEL_SHIFT_Z = 30.0  # above every real move since 2008 (largest: 18.8, Sanofi on 27 October 2023)
FLAG_COLUMNS = ["date", "instrument", "kind", "robust_z", "detail"]


def price_series(yahoo: pd.DataFrame) -> dict[str, pd.Series]:
    """Daily closes of the Yahoo price series checked by the detector (cross-checks excluded)."""
    return {
        series.instrument: raw.series_values(yahoo, series)
        for series in CATALOG
        if series.source == "yahoo" and series.role != "cross-check"
    }


def log_returns(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """One column per series, each return measured from the series' previous observed close."""
    return pd.DataFrame({instrument: np.log(values).diff() for instrument, values in closes.items()})


def robust_z(returns: pd.Series) -> pd.Series:
    """(r - median) / (1.4826 x MAD) over the previous 63 observed returns; today is not in its own window."""
    observed = returns.dropna()
    window = observed.rolling(Z_WINDOW, min_periods=Z_WINDOW // 2)
    median = window.median().shift()
    mad = window.apply(lambda values: np.median(np.abs(values - np.median(values))), raw=True).shift()
    return ((observed - median) / (MAD_SCALE * mad)).reindex(returns.index)


def next_observed(frame: pd.DataFrame) -> pd.DataFrame:
    """Each column's value on its next observed day."""
    return frame.apply(lambda column: column.dropna().shift(-1)).reindex(frame.index)


def market_median(frame: pd.DataFrame) -> pd.DataFrame:
    """For each series and day, the median of the other series that day."""
    return pd.DataFrame({column: frame.drop(columns=column).median(axis=1) for column in frame})


def detect_ticks(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Suspect days: bad ticks (extreme, reverted, not shared) and level shifts (beyond any real move)."""
    returns = log_returns(closes)
    z = returns.apply(robust_z)
    reverts = (returns + next_observed(returns)).abs() <= returns.abs() * REVERSAL_SHARE
    isolated = market_median(z).abs() < MARKET_Z
    kinds = {
        "bad tick": (z.abs() >= REVERSAL_Z) & reverts & isolated,
        "level shift": (z.abs() >= LEVEL_SHIFT_Z) & ~reverts,
    }
    frames = []
    for kind, mask in kinds.items():
        cells = mask.stack()
        cells = cells[cells].index
        frames.append(
            pd.DataFrame(
                {
                    "date": cells.get_level_values(0),
                    "instrument": cells.get_level_values(1),
                    "kind": kind,
                    "robust_z": [z.at[day, instrument] for day, instrument in cells],
                }
            )
        )
    flags = pd.concat(frames, ignore_index=True)
    details = [
        f"{kind}: robust z {value:+.1f}" + (", reverted the next day" if kind == "bad tick" else "")
        for kind, value in zip(flags["kind"], flags["robust_z"], strict=True)
    ]
    return (
        flags.assign(detail=details).sort_values(["date", "instrument"]).reset_index(drop=True)[FLAG_COLUMNS]
    )


def forest_features(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Isolation Forest inputs per series and day: r_t, r_t+1, |r_t| over the 63-day volatility, and the
    other assets' median return."""
    returns = log_returns(closes)
    volatility = returns.apply(lambda column: column.dropna().rolling(Z_WINDOW, min_periods=30).std().shift())
    features = {
        "return": returns,
        "next_return": next_observed(returns),
        "size": returns.abs() / volatility.reindex(returns.index),
        "market_return": market_median(returns),
    }
    return pd.DataFrame({name: frame.stack() for name, frame in features.items()}).dropna()
