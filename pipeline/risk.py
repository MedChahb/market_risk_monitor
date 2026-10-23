"""Risk formulas shared by the pipeline and the public app: VaR, ES, EWMA variance and the backtest tests.

Only numpy, pandas and scipy, so the app imports them without the pipeline's dependencies. VaR and ES
are positive losses in euros for a book of a given notional; returns and variances are in percent.
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy import stats

VAR_LEVEL = 0.99
ES_LEVEL = 0.975
HS_WINDOW = 250  # trading days, the regulatory standard
FHS_WINDOW = 500  # standardised returns, about two years
EWMA_DECAY = 0.94  # RiskMetrics value for daily data
NORMAL_VAR = stats.norm.ppf(VAR_LEVEL)  # 2.326
NORMAL_ES = stats.norm.pdf(stats.norm.ppf(ES_LEVEL)) / (1 - ES_LEVEL)  # 2.338: mean of the tail beyond 1.96
EXCEPTION_RATE = 1 - VAR_LEVEL
TRAFFIC_WINDOW = 250  # days in the Basel traffic-light count
YELLOW, RED = 5, 10  # exceptions in 250 days that start the yellow and red zones


def ewma_variance(returns: pd.Series) -> pd.Series:
    """Forecast made at the close of t: decay x previous forecast + (1 - decay) x r_t squared.

    EWMA has no mean reversion, so the forecast for each of the next 5 days is the same value.
    """
    return (returns**2).ewm(alpha=1 - EWMA_DECAY, adjust=False).mean()


def tail_risk(losses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """VaR 99% and ES 97.5% of samples of P&Ls (or standardised returns) along the last axis, as
    positive losses: one sample in a 1-D array, one per row in a 2-D array of windows."""
    var = -np.quantile(losses, 1 - VAR_LEVEL, axis=-1)
    threshold = np.quantile(losses, 1 - ES_LEVEL, axis=-1)
    in_tail = losses <= np.expand_dims(threshold, -1)
    return var, -np.where(in_tail, losses, 0.0).sum(axis=-1) / in_tail.sum(axis=-1)


def historical(pnl: pd.Series) -> pd.DataFrame:
    """VaR and ES computed at each close from the last 250 P&Ls, that day included."""
    var, es = tail_risk(sliding_window_view(pnl.to_numpy(), HS_WINDOW))
    return pd.DataFrame({"var": var, "es": es}, index=pnl.index[HS_WINDOW - 1 :])


def parametric(variance: pd.Series, notional: float) -> pd.DataFrame:
    """Normal VaR and ES from a 1-day variance forecast of the book return, in percent squared."""
    volatility_eur = np.sqrt(variance) / 100 * notional
    return pd.DataFrame({"var": NORMAL_VAR * volatility_eur, "es": NORMAL_ES * volatility_eur})


def filtered_historical(returns: pd.Series, variance: pd.Series, notional: float) -> pd.DataFrame:
    """FHS: the last 500 returns, each divided by the volatility forecast for its day, rescaled by the
    forecast for tomorrow. variance is indexed by forecast date: the value at t is the forecast for t+1."""
    standardised = (returns / np.sqrt(variance.shift(1))).dropna()
    windows = sliding_window_view(standardised.to_numpy(), FHS_WINDOW)  # row k ends at standardised[k + 499]
    first_row = standardised.index.searchsorted(variance.index, side="right") - FHS_WINDOW
    has_window = first_row >= 0
    var, es = tail_risk(windows[first_row[has_window]])
    scale = np.sqrt(variance.to_numpy()[has_window]) / 100 * notional
    return pd.DataFrame({"var": var * scale, "es": es * scale}, index=variance.index[has_window])


def zone(n_exceptions: float) -> str:
    """Basel traffic-light zone of an exception count over 250 days."""
    return "red" if n_exceptions >= RED else "yellow" if n_exceptions >= YELLOW else "green"


def log_likelihood(n_hits: int, n_misses: int, probability: float) -> float:
    """Bernoulli log-likelihood, with 0 x log(0) = 0."""
    hits = n_hits * np.log(probability) if n_hits else 0.0
    misses = n_misses * np.log(1 - probability) if n_misses else 0.0
    return hits + misses


def kupiec(exceptions: np.ndarray, rate: float = EXCEPTION_RATE) -> tuple[float, float]:
    """Proportion-of-failures likelihood ratio and p-value (chi-squared, 1 degree of freedom)."""
    n, x = len(exceptions), int(exceptions.sum())
    ratio = -2 * (log_likelihood(x, n - x, rate) - log_likelihood(x, n - x, x / n))
    return ratio, stats.chi2.sf(ratio, df=1)


def christoffersen(exceptions: np.ndarray) -> tuple[float, float]:
    """Independence likelihood ratio and p-value: is an exception more likely the day after another?"""
    previous, current = exceptions[:-1].astype(bool), exceptions[1:].astype(bool)
    n01, n00 = int((~previous & current).sum()), int((~previous & ~current).sum())
    n11, n10 = int((previous & current).sum()), int((previous & ~current).sum())
    if n01 + n11 == 0:
        return 0.0, 1.0  # no exception after the first day: nothing to cluster
    after_calm, after_exception = n01 / (n00 + n01), n11 / (n10 + n11) if n10 + n11 else 0.0
    overall = (n01 + n11) / (n00 + n01 + n10 + n11)
    restricted = log_likelihood(n01 + n11, n00 + n10, overall)
    unrestricted = log_likelihood(n01, n00, after_calm) + log_likelihood(n11, n10, after_exception)
    ratio = -2 * (restricted - unrestricted)
    return ratio, stats.chi2.sf(ratio, df=1)
