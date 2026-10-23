import numpy as np
import pandas as pd

from pipeline import var

DATES = pd.bdate_range("2011-01-03", periods=900)


def pnl_series(seed: int = 0) -> pd.Series:
    return pd.Series(np.random.default_rng(seed).standard_t(4, size=len(DATES)) * 50_000, index=DATES)


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
