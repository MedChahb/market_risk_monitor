"""Forecast evaluation shared by the forecasting stages: losses and the Diebold-Mariano test.

Losses are computed per date, so two models can be compared on exactly the same dates; a date where
either loss is missing is left out of a comparison.
"""

import numpy as np
import pandas as pd
from scipy import stats


def qlike(realised: pd.Series, forecast: pd.Series) -> pd.Series:
    """QLIKE loss per date, zero for a perfect forecast; missing where the realised variance is zero."""
    ratio = realised.where(realised > 0) / forecast
    return ratio - np.log(ratio) - 1


def squared_error(realised: pd.Series, forecast: pd.Series) -> pd.Series:
    return (realised - forecast) ** 2


def newey_west_lags(n: int, horizon: int) -> int:
    """Newey-West (1994) rule of thumb, and at least horizon - 1 lags for overlapping targets."""
    return max(horizon - 1, int(4 * (n / 100) ** (2 / 9)))


def newey_west_variance(values: np.ndarray, lags: int) -> float:
    """Long-run variance of a series with Bartlett weights, robust to autocorrelation."""
    centred = values - values.mean()
    n = len(centred)
    variance = centred @ centred / n
    for lag in range(1, lags + 1):
        weight = 1 - lag / (lags + 1)
        variance += 2 * weight * (centred[lag:] @ centred[:-lag]) / n
    return variance


def diebold_mariano(loss_a: pd.Series, loss_b: pd.Series, horizon: int) -> tuple[float, float]:
    """Statistic and two-sided p-value of H0 "same expected loss"; a negative statistic favours A."""
    difference = (loss_a - loss_b).dropna().to_numpy()
    variance = newey_west_variance(difference, newey_west_lags(len(difference), horizon))
    if variance <= 0:
        return 0.0, 1.0  # identical losses
    statistic = difference.mean() / np.sqrt(variance / len(difference))
    return float(statistic), float(2 * stats.norm.sf(abs(statistic)))
