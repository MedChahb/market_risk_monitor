import numpy as np
import pandas as pd
import pytest

from pipeline import calendars, costs

DAYS = calendars.sessions("XPAR", pd.Timestamp("2026-01-02"), pd.Timestamp("2026-06-30"))


def bars_from(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"high": highs, "low": lows, "close": closes}, index=DAYS[: len(highs)])


def test_corwin_schultz_recovers_the_spread_when_the_price_does_not_move():
    bid, ask = 99.95, 100.05  # every day trades only at the bid and the ask
    estimate = costs.corwin_schultz(bars_from([ask] * 3, [bid] * 3, [ask, bid, ask]))
    assert estimate.iloc[1:].to_numpy() == pytest.approx((ask - bid) / ((ask + bid) / 2))
    assert np.isnan(estimate.iloc[0])  # needs the day before


def test_overnight_gap_above_the_previous_close_is_removed_first():
    gapped = costs.corwin_schultz(bars_from([100.5, 110.5], [99.5, 109.5], [100.0, 110.0]))
    flat = costs.corwin_schultz(bars_from([100.5, 101.0], [99.5, 100.0], [100.0, 100.5]))
    assert gapped.iloc[1] == pytest.approx(flat.iloc[1])


def test_trending_two_day_range_gives_a_negative_estimate_that_is_kept():
    estimate = costs.corwin_schultz(bars_from([100.0, 101.0], [99.0, 100.0], [100.0, 101.0]))
    assert estimate.iloc[1] < 0


def test_impact_follows_the_square_root_law():
    assert costs.impact_bp(150.0, 0.04) == pytest.approx(2 * costs.impact_bp(150.0, 0.01))
    assert costs.impact_bp(150.0, 1.0) == pytest.approx(costs.IMPACT_CONSTANT * 150.0)


def test_liquidity_is_dated_on_the_next_session_and_its_spread_is_never_negative():
    rng = np.random.default_rng(0)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DAYS))))
    bars = pd.DataFrame(
        {"high": close * 1.006, "low": close * 0.994, "close": close, "adj_close": close}, index=DAYS
    )
    liquidity = costs.build_liquidity("TTE", bars)
    first_input = bars.index[costs.SPREAD_WINDOW]  # 63 estimates need 64 days
    assert (
        liquidity["date"].iloc[0] == calendars.following_sessions("XPAR", pd.DatetimeIndex([first_input]))[0]
    )
    estimates = costs.corwin_schultz(bars) * 1e4
    expected = max(0.0, estimates.loc[:first_input].tail(costs.SPREAD_WINDOW).mean())
    assert liquidity["spread_bp"].iloc[0] == pytest.approx(expected)
    assert (liquidity["spread_bp"] >= 0).all() and (liquidity["volatility_bp"] > 0).all()


def test_cost_is_half_the_spread_plus_the_impact_for_each_participation():
    liquidity = pd.DataFrame(
        {"date": [DAYS[0]], "instrument_id": ["TTE"], "spread_bp": [6.0], "volatility_bp": [150.0]}
    )
    cost = costs.build_fact_cost(liquidity).set_index("participation")
    assert list(cost.index) == list(costs.PARTICIPATIONS)
    assert cost.loc[0.01, "cost_bp"] == pytest.approx(3.0 + 150.0 * 0.1)
    assert cost.loc[0.20, "impact_bp"] == pytest.approx(150.0 * np.sqrt(0.20))
