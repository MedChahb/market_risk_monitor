import numpy as np
import pandas as pd
import pytest
from hmmlearn import hmm

from pipeline import regimes

DAYS = pd.bdate_range("2008-01-01", periods=900)


def market_rows(returns: np.ndarray, volatility: float = 0.2) -> pd.DataFrame:
    """fact_market rows for the three equity indices sharing the given daily returns."""
    frames = []
    for offset, instrument in enumerate(regimes.EQUITIES):
        noisy = returns + 0.001 * np.sin(np.arange(len(returns)) + offset)
        frames.append(
            pd.DataFrame(
                {
                    "date": DAYS[: len(returns)],
                    "instrument_id": instrument,
                    "daily_return": noisy,
                    "vol_22d": volatility,
                    "index_100": 100 * np.cumprod(1 + noisy),
                    "is_filled": False,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def two_state_model() -> hmm.GaussianHMM:
    model = hmm.GaussianHMM(2, covariance_type="full")
    model.n_features = 1  # set by fit otherwise; needed to read covars_
    model.startprob_ = np.array([0.5, 0.5])
    model.transmat_ = np.array([[0.95, 0.05], [0.05, 0.95]])
    model.means_ = np.array([[-1.0], [1.0]])
    model.covars_ = np.array([[[0.5]], [[0.5]]])
    return model


def synthetic_features(seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    """Four features that switch between three well-separated regimes every 100 days."""
    rng = np.random.default_rng(seed)
    centres = {0: [-1.5, 0.5, 0.0, -1.0], 1: [0.0, 0.0, 0.5, 0.0], 2: [1.5, -1.0, 0.0, 1.5]}
    truth = np.repeat(rng.permutation(np.tile([0, 1, 2], 3)), 100)
    values = np.array([centres[state] for state in truth]) + rng.normal(0, 0.3, (len(truth), 4))
    return pd.DataFrame(values, index=DAYS, columns=regimes.FEATURES), truth


def test_features_use_nothing_after_the_day():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 300)
    vix = pd.Series(20.0, index=DAYS[:300])
    shocked = returns.copy()
    shocked[200:] *= 5
    before = regimes.build_features(market_rows(returns), vix)
    after = regimes.build_features(market_rows(shocked), vix)
    pd.testing.assert_frame_equal(before.loc[: DAYS[199]], after.loc[: DAYS[199]])


def test_features_start_once_the_correlation_window_has_enough_days():
    returns = np.random.default_rng(1).normal(0, 0.01, 300)
    features = regimes.build_features(market_rows(returns), pd.Series(20.0, index=DAYS[:300]))
    assert features.index[0] == DAYS[39]  # the correlation needs 40 returns
    assert list(features.columns) == regimes.FEATURES


def test_states_are_ordered_from_calm_to_stress_by_volatility():
    means = np.array([[2.0, 0.0], [-1.0, 5.0], [0.5, -3.0]])
    assert list(regimes.regime_order(means)) == [1, 2, 0]


def test_filtered_probabilities_ignore_the_future():
    model = two_state_model()
    values = np.r_[np.full(20, -1.0), np.full(20, 1.0)].reshape(-1, 1)
    changed = values.copy()
    changed[30:] = -3.0
    first = regimes.filtered_probabilities(model, values)
    second = regimes.filtered_probabilities(model, changed)
    np.testing.assert_allclose(first[:30], second[:30])
    np.testing.assert_allclose(first.sum(axis=1), 1.0)
    assert first[15, 0] > 0.99 and first[35, 1] > 0.99


def test_full_history_hmm_recovers_synthetic_regimes():
    features, truth = synthetic_features()
    found = regimes.full_history_regimes(features)
    labels = found[found["method"] == "hmm"]["regime_id"].to_numpy()
    assert (labels == truth).mean() > 0.95
    probabilities = found[regimes.PROBABILITY_COLUMNS].to_numpy()
    np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)


def test_walk_forward_trains_on_past_years_only(monkeypatch):
    features, _ = synthetic_features()
    trained_until = []
    fit = regimes.fit_hmm

    def remember(values):
        trained_until.append(len(values))
        return fit(values)

    monkeypatch.setattr(regimes, "WALK_FORWARD_START", 2010)
    monkeypatch.setattr(regimes, "fit_hmm", remember)
    found = regimes.walk_forward_regimes(features)
    assert trained_until == [int((features.index < f"{year}-01-01").sum()) for year in (2010, 2011)]
    assert found.index.min() == features.index[features.index.year == 2010][0]
    assert set(found["fit"]) == {"walk_forward"}


def test_mean_durations_average_the_uninterrupted_spells():
    labels = pd.Series([0, 0, 0, 2, 2, 0, 1, 1, 1, 1, 0])
    durations = regimes.mean_durations(labels)
    assert durations[0] == pytest.approx((3 + 1 + 1) / 3)
    assert durations[1] == 4 and durations[2] == 2


def test_transition_rows_sum_to_one():
    labels = pd.Series([0, 0, 1, 1, 2, 2, 2, 0, 0, 1], index=DAYS[:10])
    found = pd.DataFrame({"regime_id": labels, "method": "hmm", "fit": "full_history"})
    transitions = regimes.build_transitions(found)
    sums = transitions.groupby("regime_from")["probability"].sum()
    np.testing.assert_allclose(sums.to_numpy(), 1.0)
    stay = transitions.set_index(["regime_from", "regime_to"])["probability"]
    assert stay[(2, 2)] == pytest.approx(2 / 3)


def test_exceptions_are_counted_by_the_regime_of_the_previous_close():
    found = pd.DataFrame({"regime_id": [0, 2, 2, 0], "method": "hmm", "fit": "full_history"}, index=DAYS[:4])
    found = pd.concat([found, found.assign(fit="walk_forward")])
    fact_backtest = pd.DataFrame(
        {"for_date": DAYS[1:4], "method_id": "fhs", "is_exception": [False, True, True]}
    )
    table = regimes.backtest_by_regime(fact_backtest, found)
    full = table[table["fit"] == "full_history"].set_index("regime_id")
    assert full.loc[0, "n_days"] == 1 and full.loc[0, "n_exceptions"] == 0  # covered by day 0, calm
    assert full.loc[2, "n_days"] == 2 and full.loc[2, "n_exceptions"] == 2
    assert full.loc[2, "expected_exceptions"] == pytest.approx(0.02)
