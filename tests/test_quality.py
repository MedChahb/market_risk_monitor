from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import quality
from pipeline.catalog import get, main_field

AS_OF = date(2026, 10, 21)
SESSIONS = quality.sessions("XPAR", pd.Timestamp("2026-09-01"), pd.Timestamp("2026-10-20"))
STAMP = pd.Timestamp("2026-10-21 18:00", tz="UTC")


def raw(instrument: str, values=None, dates=SESSIONS) -> pd.DataFrame:
    series = get(instrument)
    values = np.linspace(100, 110, len(dates)) if values is None else np.asarray(values, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
            "instrument": instrument,
            "field": main_field(series),
            "value": values,
            "source": series.source,
            "downloaded_at": STAMP,
        }
    )


def run(yahoo=None, ecb=None, fred=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    return quality.evaluate({"yahoo": yahoo, "ecb": ecb, "fred": fred}, AS_OF, "test-run")


def n_failed(fact: pd.DataFrame, instrument: str, rule: str) -> int:
    row = fact[(fact["instrument"] == instrument) & (fact["rule"] == rule)]
    assert len(row) == 1, f"{rule} was not evaluated for {instrument}"
    return int(row["n_failed"].iloc[0])


def test_clean_series_passes_every_rule():
    fact, _ = run(yahoo=raw("CAC40"))
    cac = fact[fact["instrument"] == "CAC40"]
    assert set(cac["rule"]) == {"duplicate_key", "non_positive_price", "late_data", "missing_trading_day",
                                "stale_value", "large_move"}  # fmt: skip
    assert cac["passed"].all()


def test_duplicate_row_is_critical_and_blocks_the_gate():
    table = raw("CAC40")
    fact, flags = run(yahoo=pd.concat([table, table.iloc[[3]]], ignore_index=True))
    assert n_failed(fact, "CAC40", "duplicate_key") == 2
    messages = quality.gate(fact, flags, "critical")
    assert len(messages) == 1 and messages[0].startswith(
        "CRITICAL duplicate_key | yahoo | CAC40: 2 failing row(s)"
    )


def test_non_positive_price_is_critical():
    values = np.linspace(100, 110, len(SESSIONS))
    values[5] = -1.0
    fact, _ = run(yahoo=raw("CAC40", values))
    assert n_failed(fact, "CAC40", "non_positive_price") == 1


def test_yield_out_of_range_is_critical_but_negative_yields_are_fine():
    values = np.linspace(-0.5, 0.5, len(SESSIONS))
    values[10] = 20.0
    fact, _ = run(ecb=raw("EUR10Y_AAA", values))
    assert n_failed(fact, "EUR10Y_AAA", "yield_out_of_range") == 1
    assert fact[(fact["instrument"] == "EUR10Y_AAA") & (fact["rule"] == "non_positive_price")].empty


def test_schema_failure_skips_the_other_rules_of_that_source():
    table = raw("CAC40")
    table.loc[0, "instrument"] = "TYPO"
    fact, flags = run(yahoo=table)
    assert n_failed(fact, "*", "schema") >= 1
    assert set(fact.loc[fact["source"] == "yahoo", "rule"]) == {"schema"}
    assert quality.gate(fact, flags, "critical")[0].startswith("CRITICAL schema | yahoo | *")


def test_missing_session_is_a_warning_with_its_date():
    fact, flags = run(yahoo=raw("CAC40", dates=SESSIONS.delete(7)))
    assert n_failed(fact, "CAC40", "missing_trading_day") == 1
    assert flags.loc[flags["rule"] == "missing_trading_day", "date"].iloc[0] == SESSIONS[7]
    assert quality.gate(fact, flags, "critical") == []


@pytest.mark.parametrize(("repeats", "expected"), [(2, 0), (3, 1), (4, 2)])
def test_stale_value_flags_runs_of_three_or_more(repeats, expected):
    values = np.linspace(100, 110, len(SESSIONS))
    values[10 : 10 + repeats] = values[10]
    fact, _ = run(yahoo=raw("CAC40", values))
    assert n_failed(fact, "CAC40", "stale_value") == expected


def test_large_move_is_a_warning_not_a_blocker():
    values = np.linspace(100, 110, len(SESSIONS))
    values[20:] *= 1.2
    fact, flags = run(yahoo=raw("CAC40", values))
    assert n_failed(fact, "CAC40", "large_move") == 1
    assert quality.gate(fact, flags, "critical") == []
    assert quality.gate(fact, flags, "warning")[0].startswith("WARNING large_move | yahoo | CAC40")


def test_late_data_compares_with_the_previous_session():
    fact, flags = run(yahoo=raw("CAC40", dates=SESSIONS[SESSIONS <= "2026-10-15"]))
    assert n_failed(fact, "CAC40", "late_data") == 1
    assert "expected 2026-10-20 or later" in flags.loc[flags["rule"] == "late_data", "detail"].iloc[0]


def test_missing_source_file_is_reported_as_late():
    fact, _ = run(yahoo=raw("CAC40"))
    assert n_failed(fact, "VIX", "late_data") == 1 and n_failed(fact, "US10Y2Y", "late_data") == 1


def test_fx_cross_source_flags_gaps_above_the_tolerance():
    ecb = np.full(len(SESSIONS), 1.10)
    yahoo = ecb.copy()
    yahoo[4] = 1.10 * 1.05
    fact, flags = run(yahoo=raw("EURUSD_YAHOO", yahoo), ecb=raw("EURUSD", ecb))
    assert n_failed(fact, "EURUSD_YAHOO", "fx_cross_source") == 1
    assert "(+5.00%)" in flags.loc[flags["rule"] == "fx_cross_source", "detail"].iloc[0]


def test_main_stops_with_a_readable_message_on_a_duplicate(tmp_path, caplog):
    table = raw("CAC40")
    (tmp_path / "raw" / "yahoo").mkdir(parents=True)
    pd.concat([table, table.iloc[[0]]]).to_parquet(tmp_path / "raw" / "yahoo" / "2026-10-21.parquet")
    args = ["--raw-dir", str(tmp_path / "raw"), "--dq-dir", str(tmp_path / "dq"), "--as-of", "2026-10-21"]
    assert quality.main([*args, "--run-id", "test-run"]) == 1
    assert "QUALITY GATE FAILED" in caplog.text and "CRITICAL duplicate_key | yahoo | CAC40" in caplog.text
    stored = pd.read_parquet(tmp_path / "dq" / "fact_dq.parquet")
    assert not stored.loc[stored["rule"] == "duplicate_key", "passed"].all()


def test_store_replaces_the_rows_of_the_same_run(tmp_path):
    fact, _ = run(yahoo=raw("CAC40"))
    path = tmp_path / "fact_dq.parquet"
    quality.store(fact, path, "test-run")
    quality.store(fact, path, "test-run")
    quality.store(fact.assign(run_id="other-run"), path, "other-run")
    stored = pd.read_parquet(path)
    assert len(stored) == 2 * len(fact)
