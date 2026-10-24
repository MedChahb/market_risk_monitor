import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2

from pipeline import risk

BOOK_NOTIONAL = 10_000_000
DATES = pd.bdate_range("2011-01-03", periods=900)


def pnl_series(seed: int = 0) -> pd.Series:
    return pd.Series(np.random.default_rng(seed).standard_t(4, size=len(DATES)) * 50_000, index=DATES)


def test_ewma_follows_the_riskmetrics_recursion():
    returns = pnl_series().iloc[:50] / 50_000
    forecast = risk.ewma_variance(returns)
    expected = 0.94 * forecast.iloc[29] + 0.06 * returns.iloc[30] ** 2
    assert forecast.iloc[30] == pytest.approx(expected)


def test_ewma_converges_to_the_squared_return_when_returns_are_constant():
    returns = pd.Series(2.0, index=DATES[:300])
    assert risk.ewma_variance(returns).iloc[-1] == pytest.approx(4.0)


def test_normal_multipliers_are_the_textbook_values():
    assert risk.NORMAL_VAR == pytest.approx(2.326, abs=1e-3)
    assert risk.NORMAL_ES == pytest.approx(2.338, abs=1e-3)


def test_tail_risk_reads_the_one_percent_quantile_and_the_mean_beyond_two_and_a_half():
    losses = -np.arange(1.0, 1001.0)  # P&Ls of -1 to -1000
    value_at_risk, shortfall = risk.tail_risk(losses)
    assert value_at_risk == pytest.approx(-np.quantile(losses, 0.01))
    assert shortfall == pytest.approx(np.mean(np.arange(976.0, 1001.0)))  # the 25 worst P&Ls
    assert (
        shortfall >= -np.quantile(losses, 0.025) and value_at_risk > 0
    )  # ES is beyond the VaR of its own level


def test_historical_var_uses_the_last_250_pnls_including_the_current_day():
    pnl = pnl_series()
    estimates = risk.historical(pnl)
    day = estimates.index[100]
    window = pnl.loc[:day].to_numpy()[-250:]
    assert estimates.loc[day, "var"] == pytest.approx(-np.quantile(window, 0.01))
    assert estimates.index[0] == pnl.index[249]


def test_parametric_var_scales_the_volatility_of_the_book():
    variance = pd.Series([1.0, 4.0])  # daily volatility of 1% and 2%
    estimates = risk.parametric(variance, BOOK_NOTIONAL)
    assert estimates["var"].tolist() == pytest.approx(
        [2.326 * 0.01 * BOOK_NOTIONAL, 2.326 * 0.02 * BOOK_NOTIONAL], rel=1e-3
    )
    assert (estimates["es"] > estimates["var"]).all()


def test_filtered_historical_simulation_rescales_past_shocks_to_tomorrows_volatility():
    rng = np.random.default_rng(1)
    shocks = rng.standard_t(5, size=len(DATES))
    variance = pd.Series(1.0, index=DATES)
    returns = pd.Series(shocks, index=DATES)  # volatility 1%, so the returns are the shocks
    calm = risk.filtered_historical(returns, variance, BOOK_NOTIONAL)
    stressed = risk.filtered_historical(
        returns, variance.where(variance.index != DATES[-1], 4.0), BOOK_NOTIONAL
    )
    last = DATES[-1]
    assert calm.loc[last, "var"] == pytest.approx(-np.quantile(shocks[-500:], 0.01) / 100 * BOOK_NOTIONAL)
    assert stressed.loc[last, "var"] == pytest.approx(2 * calm.loc[last, "var"])  # twice the volatility
    assert calm.index[0] == DATES[500]  # 500 standardised returns needed, the first day has none


def guide_kupiec_pof(exceptions: np.ndarray, p: float = 0.01) -> tuple[float, float]:
    """The reference implementation given in the project guide."""
    n, x = len(exceptions), int(exceptions.sum())

    def loglik(prob: float) -> float:
        a = (n - x) * np.log(1 - prob) if prob < 1 else (0.0 if x == n else -np.inf)
        b = x * np.log(prob) if prob > 0 else (0.0 if x == 0 else -np.inf)
        return a + b

    lr = -2 * (loglik(p) - loglik(x / n))
    return lr, chi2.sf(lr, df=1)


@pytest.mark.parametrize("n_exceptions", [0, 1, 3, 10, 25, 250])
def test_kupiec_matches_the_guide_reference(n_exceptions):
    flags = np.zeros(1000, dtype=bool)
    flags[np.random.default_rng(n_exceptions).choice(1000, n_exceptions, replace=False)] = True
    assert risk.kupiec(flags) == pytest.approx(guide_kupiec_pof(flags))


def test_kupiec_accepts_the_promised_rate_and_rejects_too_many_or_too_few():
    exact = np.zeros(1000, dtype=bool)
    exact[::100] = True  # 10 exceptions in 1000 days: exactly 1%
    assert risk.kupiec(exact)[0] == pytest.approx(0.0, abs=1e-9)
    too_many = np.zeros(1000, dtype=bool)
    too_many[:30] = True
    assert risk.kupiec(too_many)[1] < 0.05
    assert risk.kupiec(np.zeros(1000, dtype=bool))[1] < 0.05  # no exception in 1000 days: too cautious


def test_christoffersen_flags_exceptions_that_arrive_in_clusters():
    spread = np.zeros(1000, dtype=bool)
    spread[50::100] = True
    clustered = np.zeros(1000, dtype=bool)
    clustered[500:510] = True  # the same 10 exceptions, in one burst
    assert risk.christoffersen(spread)[1] > 0.5
    assert risk.christoffersen(clustered)[1] < 0.001


def test_christoffersen_without_exceptions_finds_nothing_to_test():
    assert risk.christoffersen(np.zeros(500, dtype=bool)) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("count", "expected"), [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"), (10, "red")]
)
def test_traffic_light_boundaries(count, expected):
    assert risk.zone(count) == expected
