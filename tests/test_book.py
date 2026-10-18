import numpy as np
import pandas as pd
import pytest

from pipeline import book

DAYS = pd.bdate_range("2026-03-02", periods=4)


def levels(**changes) -> pd.DataFrame:
    """Flat levels for every book series; keyword arguments override a column."""
    frame = pd.DataFrame(
        {"CAC40": 100.0, "SX5E": 100.0, "SPX": 100.0, "GOLD": 100.0, "EUR10Y_AAA": 2.5, "EURUSD": 1.10},
        index=DAYS,
    )
    for column, values in changes.items():
        frame[column] = values
    return frame


def position(pnl: pd.DataFrame, position_id: str, day: int) -> pd.Series:
    return pnl[(pnl["position_id"] == position_id) & (pnl["date"] == DAYS[day])].iloc[0]


def test_book_holds_ten_million_euros_in_six_positions():
    assert book.BOOK_NOTIONAL == 10_000_000 and len(book.BOOK) == 6


def test_zero_coupon_bond_uses_continuous_compounding_like_the_ecb_curve():
    assert book.zero_coupon_price(2.5) == pytest.approx(100 * np.exp(-0.25))  # 77.8801
    assert book.zero_coupon_price(0.0) == 100
    assert book.zero_coupon_price(-0.5) > 100  # negative yields: the bond is worth more than it repays


def test_bond_loses_when_the_yield_rises():
    pnl = book.position_pnl(levels(EUR10Y_AAA=[2.5, 3.5, 3.5, 3.5]))
    bond = position(pnl, "EUR_ZC10Y", 1)
    assert bond["return_eur"] == pytest.approx(np.exp(-0.1) - 1)  # -9.52% for +100 bp over 10 years
    assert bond["pnl_eur"] == pytest.approx(2_000_000 * (np.exp(-0.1) - 1))


def test_usd_position_combines_the_asset_and_the_dollar():
    eurusd = [1.10, 1.10 / 0.97, 1.10 / 0.97, 1.10 / 0.97]  # USD/EUR falls 3% on day 1
    pnl = book.position_pnl(levels(SPX=[100, 102, 102, 102], EURUSD=eurusd))
    spx = position(pnl, "SPX", 1)
    assert spx["return_local"] == pytest.approx(0.02)
    assert spx["return_fx"] == pytest.approx(-0.03)
    assert spx["return_eur"] == pytest.approx(1.02 * 0.97 - 1)
    assert spx["pnl_fx_eur"] == pytest.approx(2_000_000 * 1.02 * -0.03)
    assert spx["pnl_eur"] - spx["pnl_fx_eur"] == pytest.approx(2_000_000 * 0.02)  # the asset effect


def test_usd_cash_moves_only_with_the_dollar_and_eur_positions_not_at_all():
    pnl = book.position_pnl(levels(EURUSD=[1.10, 1.10 / 0.97, 1.10 / 0.97, 1.10 / 0.97]))
    cash = position(pnl, "USD_CASH", 1)
    assert cash["return_local"] == 0 and cash["return_eur"] == pytest.approx(-0.03)
    assert position(pnl, "CAC40", 1)["return_fx"] == 0 and position(pnl, "CAC40", 1)["pnl_eur"] == 0


def test_book_pnl_is_the_sum_of_the_positions():
    rng = np.random.default_rng(0)
    moves = {
        c: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(DAYS))) for c in ["CAC40", "SX5E", "SPX", "GOLD"]
    }
    pnl = book.position_pnl(levels(**moves, EUR10Y_AAA=[2.5, 2.6, 2.4, 2.5]))
    daily = book.book_pnl(pnl)
    expected = pnl.pivot(index="date", columns="position_id", values="pnl_eur").sum(axis=1)
    pd.testing.assert_series_equal(daily["pnl_eur"], expected, check_names=False)
    assert daily["return_book"].iloc[0] == pytest.approx(daily["pnl_eur"].iloc[0] / 10_000_000)


def test_a_day_is_kept_only_when_every_position_can_be_valued():
    pnl = book.position_pnl(levels(GOLD=[100, np.nan, 101, 102]))
    # Day 1 has no gold price and day 2 no previous one: only day 3 can be valued, for all six positions.
    assert set(pnl["date"]) == {DAYS[3]} and len(pnl) == 6


def test_a_carried_forward_day_has_zero_pnl():
    pnl = book.position_pnl(levels(CAC40=[100, 101, 101, 103]))
    assert position(pnl, "CAC40", 2)["pnl_eur"] == 0
    assert position(pnl, "CAC40", 3)["return_eur"] == pytest.approx(103 / 101 - 1)


def test_series_dimension_lists_the_book_first_then_every_position():
    series = book.build_dim_series()
    assert series["series_id"].tolist() == ["book", *(position.position_id for position in book.BOOK)]
    assert series["sort_order"].tolist() == list(range(len(book.BOOK) + 1))
    assert set(series["kind"]) == {"book", "position"}
