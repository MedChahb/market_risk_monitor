from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import calendars, quality
from tests.helpers import raw_table

AS_OF = date(2026, 10, 21)
SESSIONS = calendars.sessions("XPAR", pd.Timestamp("2026-09-01"), pd.Timestamp("2026-10-20"))


def run(yahoo=None, ecb=None, fred=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    return quality.evaluate({"yahoo": yahoo, "ecb": ecb, "fred": fred}, AS_OF, "test-run")


def n_failed(fact: pd.DataFrame, instrument: str, rule: str) -> int:
    row = fact[(fact["instrument"] == instrument) & (fact["rule"] == rule)]
    assert len(row) == 1, f"{rule} was not evaluated for {instrument}"
    return int(row["n_failed"].iloc[0])


def test_clean_series_passes_every_rule():
    fact, _ = run(yahoo=raw_table("CAC40", SESSIONS))
    cac = fact[fact["instrument"] == "CAC40"]
    expected = {
        "duplicate_key",
        "non_positive_price",
        "late_data",
        "missing_trading_day",
        "stale_value",
        "large_move",
    }
    assert set(cac["rule"]) == expected
    assert cac["passed"].all()


def test_duplicate_row_is_critical_and_blocks_the_gate():
    table = raw_table("CAC40", SESSIONS)
    fact, flags = run(yahoo=pd.concat([table, table.iloc[[3]]], ignore_index=True))
    assert n_failed(fact, "CAC40", "duplicate_key") == 2
    messages = quality.gate(fact, flags, "critical")
    assert len(messages) == 1 and messages[0].startswith(
        "CRITICAL duplicate_key | yahoo | CAC40: 2 failing row(s)"
    )


def test_non_positive_price_is_critical():
    values = np.linspace(100, 110, len(SESSIONS))
    values[5] = -1.0
    fact, _ = run(yahoo=raw_table("CAC40", SESSIONS, values))
    assert n_failed(fact, "CAC40", "non_positive_price") == 1


def test_yield_out_of_range_is_critical_but_negative_yields_are_fine():
    values = np.linspace(-0.5, 0.5, len(SESSIONS))
    values[10] = 20.0
    fact, _ = run(ecb=raw_table("EUR10Y_AAA", SESSIONS, values))
    assert n_failed(fact, "EUR10Y_AAA", "yield_out_of_range") == 1
    assert fact[(fact["instrument"] == "EUR10Y_AAA") & (fact["rule"] == "non_positive_price")].empty


def test_schema_failure_skips_the_other_rules_of_that_source():
    table = raw_table("CAC40", SESSIONS)
    table.loc[0, "instrument"] = "TYPO"
    fact, flags = run(yahoo=table)
    assert n_failed(fact, "*", "schema") >= 1
    assert set(fact.loc[fact["source"] == "yahoo", "rule"]) == {"schema"}
    assert quality.gate(fact, flags, "critical")[0].startswith("CRITICAL schema | yahoo | *")


def test_missing_session_is_a_warning_with_its_date():
    fact, flags = run(yahoo=raw_table("CAC40", SESSIONS.delete(7)))
    assert n_failed(fact, "CAC40", "missing_trading_day") == 1
    assert flags.loc[flags["rule"] == "missing_trading_day", "date"].iloc[0] == SESSIONS[7]
    assert quality.gate(fact, flags, "critical") == []


@pytest.mark.parametrize(("repeats", "expected"), [(2, 0), (3, 1), (4, 2)])
def test_stale_value_flags_runs_of_three_or_more(repeats, expected):
    values = np.linspace(100, 110, len(SESSIONS))
    values[10 : 10 + repeats] = values[10]
    fact, _ = run(yahoo=raw_table("CAC40", SESSIONS, values))
    assert n_failed(fact, "CAC40", "stale_value") == expected


def test_large_move_is_a_warning_not_a_blocker():
    values = np.linspace(100, 110, len(SESSIONS))
    values[20:] *= 1.2
    fact, flags = run(yahoo=raw_table("CAC40", SESSIONS, values))
    assert n_failed(fact, "CAC40", "large_move") == 1
    assert quality.gate(fact, flags, "critical") == []
    assert quality.gate(fact, flags, "warning")[0].startswith("WARNING large_move | yahoo | CAC40")


@pytest.mark.parametrize(("jump", "expected"), [(1.2, 0), (1.3, 1)])
def test_single_stocks_are_flagged_only_above_a_25_percent_move(jump, expected):
    values = np.linspace(100, 110, len(SESSIONS))
    values[20:] *= jump
    fact, _ = run(yahoo=raw_table("TTE", SESSIONS, values))
    assert n_failed(fact, "TTE", "large_move") == expected


def test_zero_volume_is_a_warning_for_stocks_only():
    closes = raw_table("TTE", SESSIONS)
    volumes = raw_table("TTE", SESSIONS, np.r_[0.0, np.full(len(SESSIONS) - 1, 1e6)]).assign(field="volume")
    index_volumes = raw_table("CAC40", SESSIONS, np.zeros(len(SESSIONS))).assign(field="volume")
    yahoo = pd.concat([closes, volumes, raw_table("CAC40", SESSIONS), index_volumes], ignore_index=True)
    fact, flags = run(yahoo=yahoo)
    assert n_failed(fact, "TTE", "zero_volume") == 1
    assert fact[(fact["instrument"] == "CAC40") & (fact["rule"] == "zero_volume")].empty
    assert quality.gate(fact, flags, "critical") == []


def test_late_data_compares_with_the_previous_session():
    fact, flags = run(yahoo=raw_table("CAC40", SESSIONS[SESSIONS <= "2026-10-15"]))
    assert n_failed(fact, "CAC40", "late_data") == 1
    assert "expected 2026-10-20 or later" in flags.loc[flags["rule"] == "late_data", "detail"].iloc[0]


def test_missing_source_file_is_reported_as_late():
    fact, _ = run(yahoo=raw_table("CAC40", SESSIONS))
    assert n_failed(fact, "VIX", "late_data") == 1 and n_failed(fact, "US10Y2Y", "late_data") == 1


def test_fx_cross_source_flags_gaps_above_the_tolerance():
    ecb = np.full(len(SESSIONS), 1.10)
    yahoo = ecb.copy()
    yahoo[4] = 1.10 * 1.05
    fact, flags = run(
        yahoo=raw_table("EURUSD_YAHOO", SESSIONS, yahoo), ecb=raw_table("EURUSD", SESSIONS, ecb)
    )
    assert n_failed(fact, "EURUSD_YAHOO", "fx_cross_source") == 1
    detail = flags.loc[flags["rule"] == "fx_cross_source", "detail"].iloc[0]
    assert "gap of +5.00%" in detail and "1.1000" in detail
    assert "1.1550" not in detail  # Yahoo's own level is not repeated in the message


def test_main_stops_with_a_readable_message_on_a_duplicate(tmp_path, caplog):
    table = raw_table("CAC40", SESSIONS)
    (tmp_path / "raw" / "yahoo").mkdir(parents=True)
    pd.concat([table, table.iloc[[0]]]).to_parquet(tmp_path / "raw" / "yahoo" / "2026-10-21.parquet")
    args = ["--raw-dir", str(tmp_path / "raw"), "--dq-dir", str(tmp_path / "dq"), "--as-of", "2026-10-21"]
    assert quality.main([*args, "--run-id", "test-run"]) == 1
    assert "QUALITY GATE FAILED" in caplog.text and "CRITICAL duplicate_key | yahoo | CAC40" in caplog.text
    stored = pd.read_parquet(tmp_path / "dq" / "fact_dq.parquet")
    assert not stored.loc[stored["rule"] == "duplicate_key", "passed"].all()


def test_store_replaces_the_rows_of_the_same_run(tmp_path):
    fact, _ = run(yahoo=raw_table("CAC40", SESSIONS))
    path = tmp_path / "fact_dq.parquet"
    quality.store(fact, path, "test-run")
    quality.store(fact, path, "test-run")
    quality.store(fact.assign(run_id="other-run"), path, "other-run")
    stored = pd.read_parquet(path)
    assert len(stored) == 2 * len(fact)


def test_freshness_counts_the_sessions_a_series_is_late():
    on_time = raw_table("CAC40", SESSIONS)  # ends on 2026-10-20, the session before the as-of date
    late = raw_table("SX5E", SESSIONS[SESSIONS <= "2026-10-15"])
    freshness = quality.build_freshness(
        {"yahoo": pd.concat([on_time, late]), "ecb": None, "fred": None}, AS_OF
    )
    freshness = freshness.set_index("instrument")
    assert freshness.loc["CAC40", "sessions_late"] == 0 and not freshness.loc["CAC40", "is_late"]
    assert (
        freshness.loc["SX5E", "sessions_late"] == 3 and freshness.loc["SX5E", "is_late"]
    )  # 16, 19 and 20 October
    assert pd.isna(freshness.loc["VIX", "sessions_late"]) and freshness.loc["VIX", "is_late"]  # no FRED file
