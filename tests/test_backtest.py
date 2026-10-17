import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2

from pipeline import backtest


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
    assert backtest.kupiec(flags) == pytest.approx(guide_kupiec_pof(flags))


def test_kupiec_accepts_the_promised_rate_and_rejects_too_many_or_too_few():
    exact = np.zeros(1000, dtype=bool)
    exact[::100] = True  # 10 exceptions in 1000 days: exactly 1%
    assert backtest.kupiec(exact)[0] == pytest.approx(0.0, abs=1e-9)
    too_many = np.zeros(1000, dtype=bool)
    too_many[:30] = True
    assert backtest.kupiec(too_many)[1] < 0.05
    assert backtest.kupiec(np.zeros(1000, dtype=bool))[1] < 0.05  # no exception in 1000 days: too cautious


def test_christoffersen_flags_exceptions_that_arrive_in_clusters():
    spread = np.zeros(1000, dtype=bool)
    spread[50::100] = True
    clustered = np.zeros(1000, dtype=bool)
    clustered[500:510] = True  # the same 10 exceptions, in one burst
    assert backtest.christoffersen(spread)[1] > 0.5
    assert backtest.christoffersen(clustered)[1] < 0.001


def test_christoffersen_without_exceptions_finds_nothing_to_test():
    assert backtest.christoffersen(np.zeros(500, dtype=bool)) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("count", "expected"), [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"), (10, "red")]
)
def test_traffic_light_boundaries(count, expected):
    assert backtest.zone(count) == expected


def test_an_exception_is_a_loss_strictly_above_the_var_and_the_live_day_is_left_out():
    days = pd.bdate_range("2020-01-01", periods=3)
    fact_var = pd.DataFrame({"for_date": days, "method_id": "hs", "var_99_eur": [100.0, 100.0, 100.0]})
    pnl = pd.Series([-100.0, -100.5], index=days[:2])  # no P&L yet for the last day
    fact = backtest.build_fact_backtest(fact_var, pnl)
    assert len(fact) == 2
    assert fact["is_exception"].tolist() == [False, True]


def test_the_traffic_light_counts_the_last_250_days():
    days = pd.bdate_range("2020-01-01", periods=300)
    fact_var = pd.DataFrame({"for_date": days, "method_id": "hs", "var_99_eur": 100.0})
    pnl = pd.Series(0.0, index=days)
    pnl.iloc[[10, 20, 30, 40, 260]] = -200.0
    fact = backtest.build_fact_backtest(fact_var, pnl).set_index("for_date")
    assert pd.isna(fact["exceptions_250d"].iloc[248]) and fact["exceptions_250d"].iloc[249] == 4
    assert fact["exceptions_250d"].iloc[260] == 4  # day 260 enters as day 10 leaves the window
    assert fact["zone"].iloc[260] == "green"


def test_summary_tests_the_whole_period_and_each_stress_year():
    days = pd.bdate_range("2019-01-01", "2022-12-31")
    fact_var = pd.DataFrame({"for_date": days, "method_id": "fhs", "var_99_eur": 100.0})
    pnl = pd.Series(np.where(np.arange(len(days)) % 100 == 0, -200.0, 0.0), index=days)
    table = backtest.summary(backtest.build_fact_backtest(fact_var, pnl)).set_index("period")
    assert list(table.index) == ["2019-2022", "2020", "2022"]
    assert table.loc["2019-2022", "n_exceptions"] == pytest.approx(len(days) / 100, abs=1)
    assert table.loc["2019-2022", "kupiec_p"] > 0.5
