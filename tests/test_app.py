from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import analysis

GOLD = Path(__file__).resolve().parents[1] / "data" / "gold"
DATES = pd.bdate_range("2019-01-01", periods=900)  # filtered historical simulation needs 500 days


@pytest.fixture(scope="module")
def reference():
    """The published reference book: returns, notionals, P&L and the pipeline's VaR and backtest."""
    pnl_table = pd.read_parquet(GOLD / "fact_pnl.parquet")
    returns = analysis.complete_returns(pnl_table)
    positions = pd.read_parquet(GOLD / "dim_position.parquet").set_index("position_id")["notional_eur"]
    fact_var = pd.read_parquet(GOLD / "fact_var.parquet").assign(
        for_date=lambda d: pd.to_datetime(d["for_date"])
    )
    return {
        "returns": returns,
        "positions": positions,
        "pnl": analysis.book_pnl(returns, positions),
        "published_pnl": pnl_table.assign(date=pd.to_datetime(pnl_table["date"]))
        .groupby("date")["pnl_eur"]
        .sum(),
        "fact_var": fact_var,
        "summary": pd.read_parquet(GOLD / "fact_backtest_summary.parquet"),
    }


def synthetic_returns(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.standard_t(4, size=(len(DATES), 2)) * 0.01, index=DATES, columns=["A", "B"])


def test_the_reference_notionals_reproduce_the_published_book_pnl(reference):
    pnl, published = reference["pnl"], reference["published_pnl"]
    pd.testing.assert_series_equal(pnl, published.loc[pnl.index], check_names=False, rtol=1e-9)


def test_historical_and_ewma_vars_match_the_pipeline_for_the_reference_book(reference):
    estimates = analysis.var_estimates(reference["pnl"], analysis.gross_notional(reference["positions"]))
    fact_var = reference["fact_var"]
    published = fact_var[fact_var["for_date"] == fact_var["for_date"].max()].set_index("method_id")[
        "var_99_eur"
    ]
    assert estimates["hs"]["var"].iloc[-1] == pytest.approx(published["hs"], rel=1e-9)
    assert estimates["param_ewma"]["var"].iloc[-1] == pytest.approx(published["param_ewma"], rel=1e-9)


def test_backtest_counts_the_pipelines_exceptions_for_the_reference_book(reference):
    pnl = reference["pnl"]
    estimates = analysis.var_estimates(pnl, analysis.gross_notional(reference["positions"]))
    table = analysis.backtest(pnl, estimates, "2012-01-01", str(pnl.index[-1].date()))
    summary = reference["summary"]
    whole = summary[summary["period"].str.contains("-")].set_index("method_id")
    assert table.loc["Historical simulation", "exceptions"] == whole.loc["hs", "n_exceptions"]
    assert table.loc["Parametric (EWMA)", "exceptions"] == whole.loc["param_ewma", "n_exceptions"]


def test_a_day_is_tested_against_the_var_of_the_previous_close():
    pnl = pd.Series([0.0, -5.0, -15.0], index=DATES[:3])
    estimates = pd.DataFrame({"var": [10.0, 10.0, 20.0]}, index=DATES[:3])
    assert analysis.covering_var(pnl, estimates).tolist()[1:] == [10.0, 10.0]
    assert analysis.exception_days(pnl, estimates).index.tolist() == [DATES[2]]


def test_a_short_position_gains_when_its_market_falls():
    returns = pd.DataFrame({"A": [-0.02]}, index=DATES[:1])
    assert analysis.book_pnl(returns, pd.Series({"A": -1_000_000.0})).iloc[0] == pytest.approx(20_000.0)


def test_the_var_scales_with_the_book():
    returns = synthetic_returns()
    small, large = pd.Series({"A": 1e6, "B": 1e6}), pd.Series({"A": 3e6, "B": 3e6})
    small_var = analysis.latest(analysis.var_estimates(analysis.book_pnl(returns, small), 2e6))
    large_var = analysis.latest(analysis.var_estimates(analysis.book_pnl(returns, large), 6e6))
    pd.testing.assert_frame_equal(large_var, 3 * small_var)


def test_the_traffic_light_needs_250_days():
    returns = synthetic_returns(1)
    notionals = pd.Series({"A": 1e6, "B": 1e6})
    pnl = analysis.book_pnl(returns, notionals)
    estimates = analysis.var_estimates(pnl, 2e6)
    short = analysis.backtest(pnl, estimates, str(DATES[-100].date()), str(DATES[-1].date()))
    long = analysis.backtest(pnl, estimates, str(DATES[-300].date()), str(DATES[-1].date()))
    assert short["zone"].isna().all() and long["zone"].notna().all()


def test_stress_replays_each_window_on_the_book(reference):
    returns, positions = reference["returns"], reference["positions"]
    table = analysis.stress(returns, positions, var_99=100_000.0).set_index("scenario")
    covid = next(scenario for scenario in analysis.SCENARIOS if scenario.name == "Covid crash")
    window = analysis.book_pnl(returns.loc[covid.start : covid.end], positions)
    assert table.loc["Covid crash", "cumulative_pnl"] == pytest.approx(window.sum())
    assert table.loc["Covid crash", "worst_day_in_vars"] == pytest.approx(-window.min() / 100_000.0)
    contributions = analysis.contributions(returns, positions, covid)
    assert contributions.sum() == pytest.approx(window.sum())
