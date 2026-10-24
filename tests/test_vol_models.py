import numpy as np
import pandas as pd
import pytest

from pipeline import vol_models

DATES = pd.bdate_range("2015-01-01", "2018-03-30")


def garch_returns(seed: int = 0) -> pd.Series:
    """Returns in percent from a GARCH(1,1) process, so volatility clusters as in market data."""
    rng = np.random.default_rng(seed)
    variance, values = 1.0, []
    for shock in rng.standard_normal(len(DATES)):
        value = np.sqrt(variance) * shock
        values.append(value)
        variance = 0.05 + 0.08 * value**2 + 0.9 * variance
    return pd.Series(values, index=DATES)


def test_target_is_the_mean_squared_return_of_the_next_five_days():
    returns = pd.Series(np.arange(1.0, 11.0), index=DATES[:10])
    target = vol_models.realised_variance(returns)
    assert target.iloc[0] == pytest.approx(np.mean(np.arange(2.0, 7.0) ** 2))
    assert target.iloc[-5:].isna().all() and target.iloc[:-5].notna().all()


def test_features_use_nothing_after_the_forecast_date():
    returns = garch_returns()
    changed = returns.copy()
    changed.iloc[600:] *= 10
    before = vol_models.build_features(returns, pd.DataFrame(index=DATES), None)
    after = vol_models.build_features(changed, pd.DataFrame(index=DATES), None)
    pd.testing.assert_frame_equal(before.iloc[:600], after.iloc[:600])


def test_test_months_start_in_2018_and_cover_each_day_once():
    months = vol_models.test_months(DATES)
    assert [start for start, _ in months] == [
        pd.Timestamp(day) for day in ("2018-01-01", "2018-02-01", "2018-03-01")
    ]
    covered = pd.DatetimeIndex(np.concatenate([days for _, days in months]))
    assert covered.equals(DATES[DATES >= "2018-01-01"])


def test_supervised_training_stops_five_rows_before_the_forecast_month(monkeypatch):
    seen = []

    class Recorder(vol_models.Har):
        def fit(self, features, log_target):
            seen.append(features.index)
            super().fit(features, log_target)

    monkeypatch.setitem(vol_models.SUPERVISED, "har", Recorder)
    returns = garch_returns()
    features = vol_models.build_features(returns, pd.DataFrame(index=DATES), None)
    months = vol_models.test_months(DATES)
    vol_models.walk_forward("har", features, vol_models.realised_variance(returns), months)
    for (month_start, _), train in zip(months, seen, strict=True):
        last_before_month = DATES[DATES < month_start][-1]
        assert train[-1] == DATES[DATES.get_loc(last_before_month) - 5]


def test_har_recovers_the_coefficients_of_an_exact_relation():
    rng = np.random.default_rng(4)
    features = pd.DataFrame(rng.normal(size=(500, 3)), columns=vol_models.HAR_COLUMNS)
    log_target = 0.2 + features.to_numpy() @ np.array([0.4, 0.3, 0.2])
    model = vol_models.Har()
    model.fit(features, log_target)
    assert model.coefficients == pytest.approx([0.2, 0.4, 0.3, 0.2])
    assert model.smearing == pytest.approx(1.0)


def test_garch_forecasts_every_test_day_and_rises_after_a_shock():
    returns = garch_returns()
    returns.loc["2018-02-14"] = 12.0
    forecast = vol_models.garch_forecasts(returns, vol_models.test_months(DATES), asymmetric=False)
    assert forecast.index.equals(DATES[DATES >= "2018-01-01"]) and (forecast > 0).all()
    assert forecast.loc["2018-02-14"] > 2 * forecast.loc["2018-02-13"]


def test_every_supervised_model_gives_positive_forecasts(monkeypatch):
    monkeypatch.setattr(vol_models.Gru, "epochs", 2)
    returns = garch_returns()
    features = vol_models.build_features(returns, pd.DataFrame(index=DATES), None)
    target = vol_models.realised_variance(returns)
    months = vol_models.test_months(DATES)[:1]
    for model_id in ("har", "xgboost", "gru"):
        forecast = vol_models.walk_forward(model_id, features, target, months)
        assert forecast.index.equals(months[0][1]) and (forecast > 0).all(), model_id


def test_exogenous_inputs_are_used_only_when_their_series_cover_every_date():
    dates = DATES[:30]
    rows = []
    for instrument, value in [("EUR10Y_AAA", 2.5), ("EUR2Y_AAA", 2.0), ("VIX", 20.0)]:
        rows += [{"date": day, "instrument_id": instrument, "value": value} for day in dates]
    silver = pd.DataFrame(rows)
    complete = vol_models.exogenous_features(silver, dates)
    assert set(complete.columns) == {"eur_slope", "log_vix"}
    assert complete["eur_slope"].iloc[0] == pytest.approx(0.5) and complete["log_vix"].iloc[
        0
    ] == pytest.approx(np.log(20))
    partial = vol_models.exogenous_features(
        silver[(silver["instrument_id"] != "VIX") | (silver["date"] > dates[5])], dates
    )
    assert "log_vix" not in partial.columns  # VIX starts late: left out rather than filled backwards


def test_book_return_is_the_total_pnl_over_the_notional():
    pnl = pd.DataFrame(
        {
            "date": ["2026-10-20", "2026-10-20"],
            "position_id": ["CAC40", "GOLD"],
            "return_eur": [0.01, -0.02],
            "pnl_eur": [20_000.0, -20_000.0],
        }
    )
    returns = vol_models.series_returns(pnl)
    assert returns.loc["2026-10-20", "CAC40"] == pytest.approx(1.0) and returns.loc["2026-10-20", "book"] == 0


def test_results_compare_each_model_with_har_on_the_same_days():
    days = pd.bdate_range("2018-01-01", periods=300)
    realised = pd.Series(np.random.default_rng(5).gamma(2.0, 0.5, size=300), index=days)
    forecasts = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": days,
                    "series_id": "book",
                    "model_id": model,
                    "forecast_var": forecast,
                    "realised_var": realised.to_numpy(),
                    "inputs": "returns",
                }
            )
            for model, forecast in [("har", np.full(300, realised.mean())), ("perfect", realised.to_numpy())]
        ]
    )
    table = vol_models.results_table(forecasts).set_index(["period", "model_id"])
    assert table.loc[("2018-2019", "perfect"), "qlike"] == pytest.approx(0.0)
    assert (
        table.loc[("2018-2019", "perfect"), "dm_stat_vs_har"] < 0
        and table.loc[("2018-2019", "perfect"), "dm_p_vs_har"] < 0.01
    )
    assert np.isnan(table.loc[("2018-2019", "har"), "dm_p_vs_har"])


def gjr_returns(seed: int = 6) -> pd.Series:
    """Returns from a GJR process: a fall raises the next variance more than a rise of the same size."""
    rng = np.random.default_rng(seed)
    variance, values = 1.0, []
    for shock in rng.standard_normal(len(DATES)):
        value = np.sqrt(variance) * shock
        values.append(value)
        variance = 0.05 + (0.02 + 0.15 * (value < 0)) * value**2 + 0.88 * variance
    return pd.Series(values, index=DATES)


def test_gjr_reacts_more_to_a_fall_than_to_a_rise_and_garch_does_not():
    months = vol_models.test_months(DATES)[1:2]  # February 2018
    shock_day = months[0][1][5]
    responses = {}
    for asymmetric in (False, True):
        after = {}
        for sign in (-1, 1):
            returns = gjr_returns()
            returns.loc[shock_day] = sign * 6.0
            after[sign] = vol_models.garch_forecasts(returns, months, asymmetric).loc[shock_day]
        responses[asymmetric] = after
    assert responses[True][-1] > 1.2 * responses[True][1]
    assert responses[False][-1] == pytest.approx(responses[False][1])


def test_range_terms_are_added_only_for_positions_with_prices_for_a_range():
    returns = garch_returns()
    ranges = returns**2 * 0.8
    with_range = vol_models.build_features(returns, pd.DataFrame(index=DATES), ranges)
    assert set(vol_models.RANGE_COLUMNS) <= set(with_range.columns)
    assert with_range["log_range_d"].iloc[0] == pytest.approx(np.log(ranges.iloc[0] + vol_models.EPSILON))
    without = vol_models.build_features(returns, pd.DataFrame(index=DATES), None)
    assert not set(vol_models.RANGE_COLUMNS) & set(without.columns)


def test_har_range_is_skipped_for_a_series_without_ranges():
    forecasts = vol_models.forecast_series(
        "USD_CASH", garch_returns(), pd.DataFrame(index=DATES), None, ["har_range"]
    )
    assert forecasts.empty


def test_har_range_regresses_on_the_range_terms():
    returns = garch_returns()
    forecasts = vol_models.forecast_series(
        "CAC40", returns, pd.DataFrame(index=DATES), returns**2 * 0.8, ["har_range"]
    )
    assert (
        set(forecasts["inputs"]) == {",".join(vol_models.RANGE_COLUMNS)}
        and (forecasts["forecast_var"] > 0).all()
    )


def test_position_ranges_count_a_day_without_a_session_as_zero():
    dates = DATES[:4]
    daily_range = pd.DataFrame(
        {"date": [dates[0], dates[1], dates[3]], "instrument_id": "CAC40", "range_variance": [1.0, 2.0, 3.0]}
    )
    ranges = vol_models.position_ranges(daily_range, dates)
    assert list(ranges) == ["CAC40"]  # positions without a range are absent
    assert ranges["CAC40"].tolist() == [1.0, 2.0, 0.0, 3.0]


def test_a_model_that_stops_early_does_not_cut_the_other_models_history():
    days = pd.bdate_range("2018-01-01", "2018-12-31")
    rng = np.random.default_rng(5)
    rows = []
    for model, last in [("har", days[-1]), ("gjr", days[-1]), ("gru", pd.Timestamp("2018-06-29"))]:
        kept = days[days <= last]
        rows.append(
            pd.DataFrame(
                {
                    "date": kept,
                    "series_id": "book",
                    "model_id": model,
                    "forecast_var": rng.uniform(0.5, 1.5, len(kept)),
                    "realised_var": 1.0,
                    "inputs": "",
                }
            )
        )
    table = vol_models.results_table(pd.concat(rows, ignore_index=True)).set_index("model_id")
    assert table.loc["gjr", "n_days"] == len(days)
    assert table.loc["gru", "n_days"] == int((days <= "2018-06-29").sum())
    assert not np.isnan(table.loc["gru", "dm_p_vs_har"])
