import numpy as np
import pandas as pd
import pytest

from pipeline import backtest


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
