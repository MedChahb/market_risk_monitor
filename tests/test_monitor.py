import numpy as np
import pandas as pd
import pytest

from pipeline import config, monitor

DAYS = pd.bdate_range("2016-01-01", periods=600)


def test_psi_is_zero_for_the_same_distribution_and_large_for_a_shift():
    rng = np.random.default_rng(0)
    training = pd.Series(rng.normal(0, 1, 5000))
    assert monitor.psi(training, pd.Series(rng.normal(0, 1, 5000))) < 0.02
    assert monitor.psi(training, pd.Series(rng.normal(1.5, 1, 500))) > monitor.PSI_SIGNIFICANT


def test_psi_stays_finite_when_recent_values_fill_a_single_bin():
    training = pd.Series(np.linspace(0, 1, 1000))
    value = monitor.psi(training, pd.Series(np.full(50, 0.99)))
    assert np.isfinite(value) and value > monitor.PSI_SIGNIFICANT


@pytest.mark.parametrize(
    ("value", "status"),
    [(0.05, "stable"), (0.10, "stable"), (0.2, "moderate"), (0.25, "moderate"), (0.3, "significant")],
)
def test_drift_status_follows_the_usual_thresholds(value, status):
    assert monitor.drift_status(value) == status


def test_the_standardised_return_uses_the_previous_days_volatility():
    returns = pd.Series(np.random.default_rng(1).normal(0, 1, len(DAYS)), index=DAYS)
    shocked = returns.copy()
    shocked.iloc[300] = 20.0
    before, after = monitor.drift_features(returns), monitor.drift_features(shocked)
    assert after["standardised_return"].iloc[300] > 10  # today's shock is not in its own denominator
    pd.testing.assert_series_equal(
        before["standardised_return"].iloc[:300], after["standardised_return"].iloc[:300]
    )


def test_drift_compares_the_last_250_sessions_with_the_years_before_2018():
    returns = pd.Series(
        np.random.default_rng(2).normal(0, 1, 1200), index=pd.bdate_range("2014-01-01", periods=1200)
    )
    drift = monitor.measure_drift(
        monitor.drift_features(returns), "run", pd.Timestamp("2026-01-01", tz="UTC")
    )
    assert set(drift["feature"]) == set(monitor.DRIFT_FEATURES.values())
    assert (drift["window_end"] == returns.index[-1]).all()
    assert (drift["window_start"] == returns.index[-250]).all()


def test_rolling_errors_average_the_last_63_sessions():
    days = DAYS[:100]
    forecasts = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": days,
                    "series_id": "book",
                    "model_id": model,
                    "forecast_var": 1.0,
                    "realised_var": realised,
                }
            )
            for model, realised in [("gjr", 1.0), ("har", 2.0)]
        ]
    )
    volume = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": days,
                    "instrument_id": "TTE",
                    "model_id": model,
                    "forecast_vs_adv": forecast,
                    "actual_vs_adv": 1.0,
                }
            )
            for model, forecast in [("xgboost_volume", 1.0), ("adv20", np.e)]
        ]
    )
    table = (
        monitor.rolling_errors(forecasts, volume)
        .set_index(["metric", "model_id", "date"])["value"]
        .sort_index()
    )
    assert table.loc[("qlike_63d_book_volatility", "gjr")].iloc[0] == pytest.approx(0.0)
    assert table.loc[("qlike_63d_book_volatility", "har")].iloc[0] == pytest.approx(2 - np.log(2) - 1)
    assert table.loc[("mse_log_63d_volume", "adv20")].iloc[0] == pytest.approx(1.0)
    assert table.loc[("qlike_63d_book_volatility", "gjr")].index[0] == days[62]


def test_a_failed_run_names_its_stage_and_counts_its_failed_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DQ_DIR", tmp_path)
    results = pd.DataFrame(
        {
            "run_id": ["r1", "r1", "r1", "r0"],
            "passed": [False, False, True, False],
            "severity": ["critical", "warning", "warning", "critical"],
        }
    )
    results.to_parquet(tmp_path / "fact_dq.parquet")
    assert monitor.quality_counts("r1") == (1, 1)
    assert monitor.quality_counts("r9") == (None, None)
    assert monitor.run_detail("nightly", "FAILURE", "Quality gate", "r1") == "failed at Quality gate"
    assert monitor.run_detail("nightly", "SUCCESS", "Publish", "r1") is None


def test_a_retrain_run_reports_the_promotion_decision(tmp_path, monkeypatch):
    path = tmp_path / "promotions.parquet"
    monkeypatch.setattr(config, "PROMOTIONS_FILE", path)
    decision = {
        "run_id": "w1",
        "champion_before": "gjr",
        "challenger": "garch",
        "champion_qlike": 1.607,
        "challenger_qlike": 1.638,
        "champion_zone": "green",
        "challenger_zone": "green",
        "promoted": False,
        "champion_after": "gjr",
    }
    pd.DataFrame([decision]).to_parquet(path)
    detail = monitor.run_detail("retrain", "SUCCESS", "Promotion", "w1")
    assert detail == "kept gjr: champion gjr QLIKE 1.607 (green), challenger garch 1.638 (green)"
