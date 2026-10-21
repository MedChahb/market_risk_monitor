from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import db, quality, transform
from pipeline.catalog import get, main_field

STAMP = pd.Timestamp("2026-05-11 18:00", tz="UTC")
XPAR = quality.sessions("XPAR", pd.Timestamp("2026-04-20"), pd.Timestamp("2026-05-08"))
XNYS = quality.sessions("XNYS", pd.Timestamp("2026-04-20"), pd.Timestamp("2026-05-08"))
LABOUR_DAY = pd.Timestamp("2026-05-01")  # Paris closed, New York open


def raw(instrument: str, dates: pd.DatetimeIndex, values=None) -> pd.DataFrame:
    series = get(instrument)
    values = np.linspace(100, 110, len(dates)) if values is None else values
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
            "instrument": instrument,
            "field": main_field(series),
            "value": np.asarray(values, dtype=float),
            "source": series.source,
            "downloaded_at": STAMP,
        }
    )


def silver_for(*tables: pd.DataFrame, ecb: pd.DataFrame | None = None) -> pd.DataFrame:
    return transform.build_silver({"yahoo": pd.concat(tables, ignore_index=True), "ecb": ecb, "fred": None})


def row(silver: pd.DataFrame, instrument: str, day: str) -> pd.Series:
    return silver[(silver["instrument_id"] == instrument) & (silver["date"] == pd.Timestamp(day))].iloc[0]


def test_reporting_days_are_days_when_paris_or_new_york_trades():
    days = transform.reporting_days(pd.Timestamp("2026-01-15"), pd.Timestamp("2026-05-08"))
    assert pd.Timestamp("2026-01-19") in days  # Martin Luther King Day: Paris open
    assert LABOUR_DAY in days  # New York open
    assert pd.Timestamp("2026-04-03") not in days  # Good Friday: both closed
    assert pd.Timestamp("2026-05-02") not in days  # Saturday


def test_closed_market_carries_the_last_value_forward():
    silver = silver_for(raw("CAC40", XPAR), raw("SPX", XNYS))
    cac = row(silver, "CAC40", "2026-05-01")
    assert cac["is_filled"] and cac["fill_reason"] == "market_closed"
    assert cac["value"] == row(silver, "CAC40", "2026-04-30")["value"]
    assert not row(silver, "SPX", "2026-05-01")["is_filled"]


def test_gap_on_an_open_session_is_filled_as_missing_in_source():
    silver = silver_for(raw("CAC40", XPAR.delete(3)), raw("SPX", XNYS))
    assert row(silver, "CAC40", str(XPAR[3].date()))["fill_reason"] == "missing_in_source"


def test_no_value_is_carried_past_the_last_observation():
    silver = silver_for(raw("CAC40", XPAR), raw("SPX", XNYS[XNYS <= "2026-05-06"]))
    assert silver.loc[silver["instrument_id"] == "SPX", "date"].max() == pd.Timestamp("2026-05-06")
    assert silver.loc[silver["instrument_id"] == "CAC40", "date"].max() == pd.Timestamp("2026-05-08")


def test_cross_check_series_stays_out_of_silver():
    silver = silver_for(raw("CAC40", XPAR), raw("EURUSD_YAHOO", XPAR))
    assert set(silver["instrument_id"]) == {"CAC40"}


def test_dim_date_covers_full_years_with_a_trading_day_index():
    trading = transform.reporting_days(pd.Timestamp("2025-01-02"), pd.Timestamp("2026-05-08"))
    dim = transform.build_dim_date(trading, date(2026, 5, 11)).set_index("date")
    assert dim.index[0] == pd.Timestamp("2025-01-01") and dim.index[-1] == pd.Timestamp("2026-12-31")
    assert (dim.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    idx = dim["trading_day_index"]
    assert idx[trading].tolist() == list(range(1, len(trading) + 1))
    assert (
        idx[pd.Timestamp("2026-05-02")] == idx[pd.Timestamp("2026-05-01")]
    )  # a Saturday keeps Friday's index
    assert pd.isna(idx[pd.Timestamp("2025-01-01")]) and pd.isna(idx[pd.Timestamp("2026-05-11")])


def test_month_end_is_the_last_trading_day_of_each_month():
    trading = transform.reporting_days(pd.Timestamp("2025-01-02"), pd.Timestamp("2026-05-08"))
    dim = transform.build_dim_date(trading, date(2026, 5, 11))
    ends = dim.loc[dim["is_month_end"], "date"]
    assert len(ends) == 16  # January 2025 to April 2026; May 2026 is not over
    assert pd.Timestamp("2026-04-30") in ends.values and pd.Timestamp("2025-12-31") in ends.values


def test_fact_market_returns_index_and_licence_policy():
    yields = raw("EUR10Y_AAA", XPAR, np.linspace(2.0, 2.5, len(XPAR)))
    silver = silver_for(raw("CAC40", XPAR), raw("SPX", XNYS), ecb=yields)
    fact = transform.build_fact_market(silver)
    cac = fact[fact["instrument_id"] == "CAC40"].reset_index(drop=True)
    assert cac["index_100"].iloc[0] == 100 and cac["level"].isna().all()  # Yahoo level not published
    assert cac["daily_return"].iloc[1] == pytest.approx(cac["index_100"].iloc[1] / 100 - 1)
    assert (cac.loc[cac["is_filled"], "daily_return"] == 0).all()
    rates = fact[fact["instrument_id"] == "EUR10Y_AAA"]
    assert (
        rates["level"].notna().all()
        and rates["index_100"].isna().all()
        and rates["daily_return"].isna().all()
    )
    assert rates["change_bp"].dropna().iloc[0] == pytest.approx(
        (yields["value"].iloc[1] - yields["value"].iloc[0]) * 100
    )


def test_main_refuses_raw_data_with_a_critical_failure(tmp_path, monkeypatch):
    table = raw("CAC40", XPAR)
    (tmp_path / "yahoo").mkdir()
    pd.concat([table, table.iloc[[0]]]).to_parquet(tmp_path / "yahoo" / "2026-05-11.parquet")
    monkeypatch.setattr(db, "engine", lambda: pytest.fail("the database must not be touched"))
    assert transform.main(["--raw-dir", str(tmp_path), "--as-of", "2026-05-11"]) == 1
