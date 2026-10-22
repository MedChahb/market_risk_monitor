import numpy as np
import pandas as pd
import pytest

from pipeline import calendars, volume_models

DAYS = calendars.sessions("XPAR", pd.Timestamp("2016-01-04"), pd.Timestamp("2018-04-30"))


def synthetic_bars(seed: int = 0) -> pd.DataFrame:
    """Log volume that clusters (an AR(1) around 15) and prices that drift randomly."""
    rng = np.random.default_rng(seed)
    log_volume = np.empty(len(DAYS))
    log_volume[0] = 15.0
    for day in range(1, len(DAYS)):
        log_volume[day] = 15.0 + 0.7 * (log_volume[day - 1] - 15.0) + rng.normal(0, 0.3)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DAYS))))
    return pd.DataFrame({"adj_close": close, "volume": np.exp(log_volume).round()}, index=DAYS)


def test_calendar_flags_mark_expiries_month_ends_and_pre_holidays():
    days = pd.DatetimeIndex(["2026-03-20", "2026-03-31", "2026-04-02", "2026-04-10", "2026-04-17"])
    flags = volume_models.calendar_flags(days)
    assert list(flags["third_friday"]) == [1, 0, 0, 0, 1]
    assert list(flags["quarterly_expiry"]) == [1, 0, 0, 0, 0]  # March, not April
    assert list(flags["month_end"]) == [0, 1, 0, 0, 0]
    assert list(flags["pre_holiday"]) == [0, 0, 1, 0, 0]  # Thursday before Good Friday; not a plain Friday
    assert list(flags["weekday"]) == [4, 1, 3, 4, 4]


def test_features_use_nothing_after_the_forecast_date():
    bars = synthetic_bars()
    changed = bars.copy()
    changed.iloc[400:] *= 3
    vix = pd.Series(20.0, index=DAYS)
    before = volume_models.build_features(bars, vix)
    after = volume_models.build_features(changed, vix)
    pd.testing.assert_frame_equal(before.iloc[:400], after.iloc[:400])


def test_forecasts_cover_the_next_session_as_multiples_of_the_previous_adv():
    bars = synthetic_bars()
    forecasts = volume_models.forecast_stock("TTE", bars, pd.Series(20.0, index=DAYS))
    baseline = forecasts[forecasts["model_id"] == "adv20"].set_index("date")
    first = bars.index[bars.index >= volume_models.TEST_START][0]
    target_day = bars.index[bars.index.get_loc(first) + 1]
    adv = bars["volume"].loc[:first].tail(volume_models.ADV_WINDOW).mean()
    assert baseline.index[0] == target_day
    assert baseline["forecast_vs_adv"].eq(1.0).all()
    assert baseline.loc[target_day, "actual_vs_adv"] == pytest.approx(bars.loc[target_day, "volume"] / adv)
    assert baseline.index[-1] == calendars.following_sessions("XPAR", bars.index[-1:])[0]
    assert np.isnan(baseline["actual_vs_adv"].iloc[-1])  # the next session has not traded yet
    assert set(forecasts["model_id"]) == set(volume_models.MODELS)


def test_training_stops_one_row_before_the_forecast_month(monkeypatch):
    seen = []

    def remember(model_id, train, target, test):
        seen.append((train.index.max(), test.index.min()))
        return np.zeros(len(test))

    monkeypatch.setattr(volume_models, "fit_predict", remember)
    bars = synthetic_bars()
    features = volume_models.build_features(bars, pd.Series(dtype=float))
    target = np.log(bars["volume"]).shift(-1)
    volume_models.walk_forward("har_volume", features, target, volume_models.test_months(bars.index))
    for last_train, first_test in seen:
        position = bars.index.get_loc(first_test)
        assert last_train == bars.index[position - 2]


def test_har_on_log_volume_beats_the_adv_on_clustered_volume():
    bars = synthetic_bars()
    forecasts = volume_models.forecast_stock("TTE", bars, pd.Series(20.0, index=DAYS))
    table = volume_models.results_table(forecasts).set_index("model_id")
    assert table.loc["har_volume", "mse_log"] < table.loc["adv20", "mse_log"]
    assert table.loc["har_volume", "dm_stat_vs_adv"] < 0
    assert np.isnan(table.loc["adv20", "dm_p_vs_adv"])


def test_losses_are_zero_for_a_perfect_forecast():
    dates = DAYS[-30:]
    actual = np.linspace(0.8, 1.3, len(dates))
    frames = [
        pd.DataFrame(
            {
                "date": dates,
                "instrument_id": "TTE",
                "model_id": model,
                "forecast_vs_adv": forecast,
                "actual_vs_adv": actual,
            }
        )
        for model, forecast in [("adv20", np.ones(len(dates))), ("har_volume", actual)]
    ]
    table = volume_models.results_table(pd.concat(frames, ignore_index=True)).set_index("model_id")
    assert table.loc["har_volume", "mse_log"] == pytest.approx(0.0)
    assert table.loc["har_volume", "mape"] == pytest.approx(0.0)
    assert table.loc["adv20", "mape"] == pytest.approx(np.mean(np.abs(1 - actual) / actual))
