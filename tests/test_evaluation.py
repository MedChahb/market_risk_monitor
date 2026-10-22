import numpy as np
import pandas as pd
import pytest

from pipeline import evaluation


def test_qlike_is_zero_for_a_perfect_forecast():
    realised = pd.Series([1.0, 2.0, 0.5])
    assert evaluation.qlike(realised, realised).tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_qlike_punishes_under_forecasting_more_than_over_forecasting():
    realised = pd.Series([2.0])
    under = evaluation.qlike(realised, pd.Series([1.0])).iloc[0]  # forecast half the realised variance
    over = evaluation.qlike(realised, pd.Series([4.0])).iloc[0]  # forecast twice the realised variance
    assert under == pytest.approx(1 - np.log(2)) and over == pytest.approx(np.log(2) - 0.5)
    assert under > over > 0


def test_qlike_is_missing_when_the_realised_variance_is_zero():
    assert evaluation.qlike(pd.Series([0.0]), pd.Series([1.0])).isna().all()


def test_newey_west_without_lags_is_the_plain_variance():
    values = np.random.default_rng(0).normal(size=500)
    assert evaluation.newey_west_variance(values, 0) == pytest.approx(values.var())


def test_newey_west_widens_the_variance_of_positively_autocorrelated_series():
    noise = np.random.default_rng(1).normal(size=2001)
    overlapping = np.convolve(noise, np.ones(5) / 5, mode="valid")  # like 5-day overlapping targets
    assert evaluation.newey_west_variance(overlapping, 4) > 2 * overlapping.var()


def test_newey_west_lags_cover_the_overlap_of_the_target():
    assert evaluation.newey_west_lags(50, horizon=5) == 4
    assert evaluation.newey_west_lags(2000, horizon=5) == 7


def test_diebold_mariano_detects_a_clearly_better_model():
    rng = np.random.default_rng(2)
    loss_b = pd.Series(rng.gamma(2.0, 1.0, size=1000))
    loss_a = loss_b * 0.7 + rng.normal(0, 0.05, size=1000)
    statistic, p_value = evaluation.diebold_mariano(loss_a, loss_b, horizon=5)
    assert statistic < 0 and p_value < 0.01


def test_diebold_mariano_finds_no_difference_between_equivalent_models():
    rng = np.random.default_rng(3)
    loss_a, loss_b = pd.Series(rng.gamma(2.0, 1.0, size=1000)), pd.Series(rng.gamma(2.0, 1.0, size=1000))
    assert evaluation.diebold_mariano(loss_a, loss_b, horizon=5)[1] > 0.05


def test_diebold_mariano_compares_only_dates_where_both_losses_exist():
    loss_a = pd.Series([1.0, np.nan, 1.0, 1.0])
    loss_b = pd.Series([1.0, 5.0, 1.0, 1.0])
    assert evaluation.diebold_mariano(loss_a, loss_b, horizon=1) == (0.0, 1.0)
