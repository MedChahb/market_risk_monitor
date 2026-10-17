import numpy as np
import pandas as pd
import pytest

from pipeline import var
from pipeline.book import BOOK_NOTIONAL

DATES = pd.bdate_range("2011-01-03", periods=900)


def pnl_series(seed: int = 0) -> pd.Series:
    return pd.Series(np.random.default_rng(seed).standard_t(4, size=len(DATES)) * 50_000, index=DATES)


def test_normal_multipliers_are_the_textbook_values():
    assert var.NORMAL_VAR == pytest.approx(2.326, abs=1e-3)
    assert var.NORMAL_ES == pytest.approx(2.338, abs=1e-3)


def test_tail_risk_reads_the_one_percent_quantile_and_the_mean_beyond_two_and_a_half():
    losses = -np.arange(1.0, 1001.0)  # P&Ls of -1 to -1000
    value_at_risk, shortfall = var.tail_risk(losses)
    assert value_at_risk == pytest.approx(-np.quantile(losses, 0.01))
    assert shortfall == pytest.approx(np.mean(np.arange(976.0, 1001.0)))  # the 25 worst P&Ls
    assert (
        shortfall >= -np.quantile(losses, 0.025) and value_at_risk > 0
    )  # ES is beyond the VaR of its own level


def test_historical_var_uses_the_last_250_pnls_including_the_current_day():
    pnl = pnl_series()
    estimates = var.historical(pnl)
    day = estimates.index[100]
    window = pnl.loc[:day].to_numpy()[-250:]
    assert estimates.loc[day, "var"] == pytest.approx(-np.quantile(window, 0.01))
    assert estimates.index[0] == pnl.index[249]


def test_parametric_var_scales_the_volatility_of_the_book():
    variance = pd.Series([1.0, 4.0])  # daily volatility of 1% and 2%
    estimates = var.parametric(variance)
    assert estimates["var"].tolist() == pytest.approx(
        [2.326 * 0.01 * BOOK_NOTIONAL, 2.326 * 0.02 * BOOK_NOTIONAL], rel=1e-3
    )
    assert (estimates["es"] > estimates["var"]).all()


def test_filtered_historical_simulation_rescales_past_shocks_to_tomorrows_volatility():
    rng = np.random.default_rng(1)
    shocks = rng.standard_t(5, size=len(DATES))
    variance = pd.Series(1.0, index=DATES)
    returns = pd.Series(shocks, index=DATES)  # volatility 1%, so the returns are the shocks
    calm = var.filtered_historical(returns, variance)
    stressed = var.filtered_historical(returns, variance.where(variance.index != DATES[-1], 4.0))
    last = DATES[-1]
    assert calm.loc[last, "var"] == pytest.approx(-np.quantile(shocks[-500:], 0.01) / 100 * BOOK_NOTIONAL)
    assert stressed.loc[last, "var"] == pytest.approx(2 * calm.loc[last, "var"])  # twice the volatility
    assert calm.index[0] == DATES[500]  # 500 standardised returns needed, the first day has none


def test_a_figure_computed_at_the_close_covers_the_next_day():
    estimates = pd.DataFrame(
        {"var": [1.0, 2.0, 3.0]}, index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"])
    )
    dated = var.to_for_date(estimates, estimates.index)
    assert list(dated.index) == list(pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"]))


def test_the_var_for_a_day_does_not_use_that_days_pnl():
    pnl = pnl_series(2)
    variances = {name: pd.Series(1.0, index=DATES) for name in ("ewma", "garch", "gjr")}
    fact = var.build_fact_var(pnl, variances).set_index(["for_date", "method_id"])
    target_day = DATES[700]
    shocked = pnl.copy()
    shocked.loc[target_day] = -5_000_000
    changed = var.build_fact_var(shocked, variances).set_index(["for_date", "method_id"])
    assert changed.loc[(target_day, "hs"), "var_99_eur"] == fact.loc[(target_day, "hs"), "var_99_eur"]
    assert changed.loc[(DATES[701], "hs"), "var_99_eur"] > fact.loc[(DATES[701], "hs"), "var_99_eur"]


def test_fact_var_starts_in_2012_with_positive_losses():
    pnl = pnl_series(3)
    variances = {name: pd.Series(1.0, index=DATES) for name in ("ewma", "garch", "gjr")}
    fact = var.build_fact_var(pnl, variances)
    assert fact["for_date"].min() >= var.VAR_START
    assert set(fact["method_id"]) == {"hs", "param_ewma", "param_garch", "param_champion", "fhs"}
    assert (fact["var_99_eur"] > 0).all() and (fact["es_975_eur"] > 0).all()
