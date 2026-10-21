import numpy as np
import pandas as pd
import pytest

from pipeline import anomalies, anomaly_evaluation, calendars

DAYS = calendars.sessions("XPAR", pd.Timestamp("2018-01-02"), pd.Timestamp("2020-06-30"))
INSTRUMENTS = ["CAC40", "SX5E", "TTE", "SAN", "BNP"]  # catalog series on the Paris calendar


def quiet_closes(seed: int = 0) -> dict[str, pd.Series]:
    """Five series of random-walk closes with 1% daily moves and no error."""
    rng = np.random.default_rng(seed)
    return {
        instrument: pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DAYS)))), index=DAYS)
        for instrument in INSTRUMENTS
    }


def flagged(closes: dict[str, pd.Series]) -> set[tuple[pd.Timestamp, str, str]]:
    found = anomalies.detect_ticks(closes)
    return set(zip(found["date"], found["instrument"], found["kind"], strict=True))


def test_robust_z_uses_the_previous_returns_only():
    returns = pd.Series(np.random.default_rng(1).normal(0, 0.01, 200), index=DAYS[:200])
    z = anomalies.robust_z(returns)
    window = returns.iloc[136:199]  # the 63 returns before day 199
    median = window.median()
    mad = (window - median).abs().median()
    assert z.iloc[199] == pytest.approx((returns.iloc[199] - median) / (1.4826 * mad))
    shocked = returns.copy()
    shocked.iloc[199] = 0.5
    assert anomalies.robust_z(shocked).iloc[:199].equals(z.iloc[:199])


def test_a_spike_that_reverts_on_one_series_is_a_bad_tick():
    closes = quiet_closes()
    day = DAYS[300]
    closes["TTE"].loc[day] *= 1.15
    assert flagged(closes) == {(day, "TTE", "bad tick")}


def test_a_move_shared_by_the_market_is_not_flagged():
    closes = quiet_closes()
    day = DAYS[300]
    for values in closes.values():
        values.loc[day] *= 1.15  # every series jumps and comes back: a market event
    assert flagged(closes) == set()


def test_a_large_move_that_stays_is_not_flagged_below_the_level_shift_threshold():
    closes = quiet_closes()
    closes["SAN"].loc[DAYS[300] :] *= 0.80  # an idiosyncratic crash of 20% that does not revert
    assert flagged(closes) == set()


def test_an_unadjusted_split_is_a_level_shift():
    closes = quiet_closes()
    closes["BNP"].loc[DAYS[300] :] /= 2
    assert flagged(closes) == {(DAYS[300], "BNP", "level shift")}


def test_forest_features_pair_each_return_with_the_next_one():
    closes = quiet_closes()
    features = anomalies.forest_features(closes)
    returns = anomalies.log_returns(closes)
    day, following = DAYS[100], DAYS[101]
    assert list(features.columns) == ["return", "next_return", "size", "market_return"]
    assert features.loc[(day, "TTE"), "next_return"] == pytest.approx(returns.at[following, "TTE"])
    others = returns.loc[day, ["CAC40", "SX5E", "SAN", "BNP"]].median()
    assert features.loc[(day, "TTE"), "market_return"] == pytest.approx(others)


def test_injection_is_reproducible_and_places_every_error():
    clean = quiet_closes()
    data, errors = anomaly_evaluation.inject(clean, seed=3, n_per_type=5)
    again, same_errors = anomaly_evaluation.inject(clean, seed=3, n_per_type=5)
    assert errors.equals(same_errors)
    assert errors["error_type"].value_counts().to_dict() == dict.fromkeys(anomaly_evaluation.ERROR_TYPES, 5)
    for instrument in INSTRUMENTS:
        pd.testing.assert_series_equal(data[instrument], again[instrument])


def test_injected_errors_change_the_prices_as_described():
    clean = quiet_closes()
    data, errors = anomaly_evaluation.inject(clean, seed=4, n_per_type=3)
    split = errors[errors["error_type"] == "split"].iloc[0]
    ratio = data[split.instrument] / clean[split.instrument]
    before = ratio.loc[: split.date].iloc[:-1]
    assert ratio.loc[split.date] == pytest.approx(before.iloc[-1] / 2)
    missing = errors[errors["error_type"] == "missing_days"]
    for row in missing.itertuples():
        assert row.cells[0] not in data[row.instrument].index


def test_score_counts_a_flag_on_the_session_after_the_error():
    errors = pd.DataFrame(
        {
            "error_type": ["spike", "split"],
            "instrument": ["TTE", "SAN"],
            "date": [DAYS[10], DAYS[20]],
            "cells": [[DAYS[10], DAYS[11]], [DAYS[20], DAYS[21]]],
        }
    )
    flags = {(DAYS[11], "TTE"), (DAYS[50], "BNP")}
    result = anomaly_evaluation.score(flags, errors)
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall_spike"] == 1.0 and result["recall_split"] == 0.0
    assert result["n_flags"] == 2
