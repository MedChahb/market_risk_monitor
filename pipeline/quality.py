"""Data quality gate for the raw tables.

Runs the rules on the latest raw file of each source and stores the results in data/dq/:
fact_dq (one row per run, instrument and rule), dq_flags (one row per flagged observation) and
dq_freshness (one row per run and series: last date against the last expected session).
Exits with code 1 when a rule of the blocking severity fails, so bad data never reaches silver.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa

from pipeline import calendars, config, files, raw
from pipeline.catalog import CATALOG, FIELDS, SOURCES, Series, by_source, get, main_field

log = logging.getLogger("quality")

MAX_DAILY_MOVE = 0.15  # largest real daily move since 2008: 12.4% (Euro Stoxx 50, 12 March 2020)
YIELD_RANGE = (-2.0, 15.0)  # percent; AAA 10-year range since 2008: -0.82% to 4.78%
STALE_DAYS = 3
FX_TOLERANCE = 0.02  # about 3.6 daily std devs of EUR/USD; the ECB fixes at 14:15 CET, Yahoo later

CRITICAL, WARNING = "critical", "warning"
RULES = {
    "schema": CRITICAL,
    "duplicate_key": CRITICAL,
    "non_positive_price": CRITICAL,
    "yield_out_of_range": CRITICAL,
    "missing_trading_day": WARNING,
    "stale_value": WARNING,
    "large_move": WARNING,
    "late_data": WARNING,
    "fx_cross_source": WARNING,
}
FLAG_COLUMNS = ["date", "instrument", "field", "value", "detail"]
FACT_DQ_COLUMNS = ["run_id", "date", "source", "instrument", "rule", "severity", "passed", "n_failed"]
DQ_FLAGS_COLUMNS = ["run_id", "date", "source", "instrument", "field", "rule", "severity", "value", "detail"]
FRESHNESS_COLUMNS = ["source", "instrument", "last_date", "expected_date", "sessions_late", "is_late"]


def is_utc(column: pd.Series) -> bool:
    return isinstance(column.dtype, pd.DatetimeTZDtype) and str(column.dtype.tz) == "UTC"


RAW_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column("datetime64[ns]"),
        "instrument": pa.Column(str, pa.Check.isin([s.instrument for s in CATALOG])),
        "field": pa.Column(str, pa.Check.isin(sorted({f for fields in FIELDS.values() for f in fields}))),
        "value": pa.Column(float, pa.Check(np.isfinite, error="finite")),
        "source": pa.Column(str, pa.Check.isin(SOURCES)),
        "downloaded_at": pa.Column(checks=pa.Check(is_utc, error="UTC timestamp")),
    },
    strict=True,
)


def applies(rule: str, series: Series) -> bool:
    if rule == "non_positive_price":
        return series.asset_class != "rates"
    if rule == "yield_out_of_range":
        return series.unit == "percent per annum"
    if rule == "missing_trading_day":
        return series.calendar is not None
    if rule == "large_move":  # volatility indices and rates move by more than 15% routinely
        return series.asset_class in ("equity index", "commodity", "fx")
    if rule == "fx_cross_source":
        return series.instrument == "EURUSD_YAHOO"
    return True


def empty_flags() -> pd.DataFrame:
    dtypes = ["datetime64[ns]", str, str, float, str]
    return pd.DataFrame({column: pd.Series(dtype=t) for column, t in zip(FLAG_COLUMNS, dtypes, strict=True)})


def flags_from_rows(rows: pd.DataFrame, detail: str) -> pd.DataFrame:
    return rows.assign(detail=detail)[FLAG_COLUMNS]


def flags_from_values(values: pd.Series, series: Series, detail: str | list[str]) -> pd.DataFrame:
    frame = values.rename("value").rename_axis("date").reset_index()
    return frame.assign(instrument=series.instrument, field=main_field(series), detail=detail)[FLAG_COLUMNS]


def check_schema(table: pd.DataFrame) -> pd.DataFrame:
    try:
        RAW_SCHEMA.validate(table, lazy=True)
    except pa.errors.SchemaErrors as err:
        cases = err.failure_cases
        return pd.DataFrame(
            {
                "date": pd.NaT,
                "instrument": "*",
                "field": cases["column"].astype(str),
                "value": np.nan,
                "detail": cases["check"].astype(str) + ": " + cases["failure_case"].astype(str),
            }
        )[FLAG_COLUMNS]
    return empty_flags()


def check_duplicates(table: pd.DataFrame) -> pd.DataFrame:
    duplicates = table[table.duplicated(["date", "instrument", "field"], keep=False)]
    return flags_from_rows(duplicates, "several rows share this (date, instrument, field)")


def check_non_positive(table: pd.DataFrame) -> pd.DataFrame:
    prices = table[table["field"] != "volume"]
    return flags_from_rows(prices[prices["value"] <= 0], "price is zero or negative")


def check_yield_range(table: pd.DataFrame) -> pd.DataFrame:
    low, high = YIELD_RANGE
    outside = table[(table["value"] < low) | (table["value"] > high)]
    return flags_from_rows(outside, f"yield outside {low}% to {high}%")


def check_missing_days(values: pd.Series, series: Series) -> pd.DataFrame:
    open_days = calendars.sessions(series.calendar, values.index.min(), values.index.max())
    missing = pd.Series(np.nan, index=open_days.difference(values.index))
    return flags_from_values(missing, series, f"no data on a {series.calendar} session")


def check_stale(values: pd.Series, series: Series) -> pd.DataFrame:
    same = values.eq(values.shift())
    run_length = same.groupby((~same).cumsum()).cumsum() + 1
    stale = run_length[run_length >= STALE_DAYS]
    details = [f"same value {n} days in a row" for n in stale.astype(int)]
    return flags_from_values(values[stale.index], series, details)


def check_large_move(values: pd.Series, series: Series) -> pd.DataFrame:
    moves = values.pct_change()
    large = moves[moves.abs() > MAX_DAILY_MOVE]
    return flags_from_values(
        values[large.index], series, [f"{move:+.1%} vs previous value" for move in large]
    )


def check_late(values: pd.Series, series: Series, as_of: date) -> pd.DataFrame:
    expected = calendars.previous_session(series.calendar, as_of)
    if values.empty:
        no_data = pd.Series([np.nan], index=[pd.Timestamp(as_of)])
        return flags_from_values(no_data, series, "no data for this series")
    if values.index.max() >= expected:
        return empty_flags()
    detail = f"last date {values.index.max():%Y-%m-%d}, expected {expected:%Y-%m-%d} or later"
    return flags_from_values(values.tail(1), series, detail)


def check_fx_cross_source(yahoo: pd.Series, ecb: pd.Series, series: Series) -> pd.DataFrame:
    """Yahoo EUR/USD against the ECB fixing; the detail quotes the ECB rate only, Yahoo levels stay private."""
    both = pd.concat({"yahoo": yahoo, "ecb": ecb}, axis=1, join="inner")
    gap = both["yahoo"] / both["ecb"] - 1
    outside = both[gap.abs() > FX_TOLERANCE]
    gaps = gap[outside.index]
    details = [
        f"gap of {g:+.2%} with the ECB rate {e:.4f}" for g, e in zip(gaps, outside["ecb"], strict=True)
    ]
    return flags_from_values(outside["yahoo"], series, details)


def series_rules(values: pd.Series, series: Series, as_of: date) -> dict[str, pd.DataFrame]:
    """The rules that look at one series over time, keyed by rule name."""
    found = {"late_data": check_late(values, series, as_of)}
    if values.empty:
        return found
    for rule, check in [
        ("missing_trading_day", check_missing_days),
        ("stale_value", check_stale),
        ("large_move", check_large_move),
    ]:
        if applies(rule, series):
            found[rule] = check(values, series)
    return found


def evaluate(
    raws: dict[str, pd.DataFrame | None], as_of: date, run_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply every rule; return (fact_dq, dq_flags)."""
    results, flagged = [], []

    def record(source: str, instrument: str, rule: str, found: pd.DataFrame) -> None:
        results.append({"source": source, "instrument": instrument, "rule": rule, "n_failed": len(found)})
        if len(found):
            flagged.append(found.assign(source=source, rule=rule))

    valid = {}
    for source in SOURCES:
        table = raws.get(source)
        if table is None:
            for series in by_source(source):
                record(
                    source, series.instrument, "late_data", check_late(pd.Series(dtype=float), series, as_of)
                )
            continue
        schema_flags = check_schema(table)
        record(source, "*", "schema", schema_flags)
        if len(schema_flags):
            continue  # values cannot be trusted: the other rules are skipped for this source
        valid[source] = table
        table_rules = {
            "duplicate_key": check_duplicates(table),
            "non_positive_price": check_non_positive(table),
            "yield_out_of_range": check_yield_range(table),
        }
        for series in by_source(source):
            for rule, found in table_rules.items():
                if applies(rule, series):
                    record(source, series.instrument, rule, found[found["instrument"] == series.instrument])
            for rule, found in series_rules(raw.series_values(table, series), series, as_of).items():
                record(source, series.instrument, rule, found)

    if "yahoo" in valid and "ecb" in valid:
        yahoo_fx, ecb_fx = get("EURUSD_YAHOO"), get("EURUSD")
        yahoo_values = raw.series_values(valid["yahoo"], yahoo_fx)
        ecb_values = raw.series_values(valid["ecb"], ecb_fx)
        found = check_fx_cross_source(yahoo_values, ecb_values, yahoo_fx)
        record("yahoo", yahoo_fx.instrument, "fx_cross_source", found)

    fact = pd.DataFrame(results)
    fact = fact.assign(
        run_id=run_id,
        date=pd.Timestamp(as_of).as_unit("ns"),
        severity=fact["rule"].map(RULES),
        passed=fact["n_failed"] == 0,
    )[FACT_DQ_COLUMNS]
    flags = pd.concat(flagged, ignore_index=True) if flagged else empty_flags().assign(source=None, rule=None)
    flags = flags.assign(
        run_id=run_id,
        date=pd.to_datetime(flags["date"]).astype("datetime64[ns]"),
        severity=flags["rule"].map(RULES),
    )[DQ_FLAGS_COLUMNS]
    return fact, flags


def gate(fact: pd.DataFrame, flags: pd.DataFrame, fail_on: str) -> list[str]:
    """Readable messages for the failed rules of a blocking severity (an empty list means the gate passes)."""
    blocking = {"critical": {CRITICAL}, "warning": {CRITICAL, WARNING}, "none": set()}[fail_on]
    messages = []
    for row in fact[~fact["passed"] & fact["severity"].isin(blocking)].itertuples():
        same_rule = (flags["rule"] == row.rule) & (flags["source"] == row.source)
        same_rule &= flags["instrument"] == row.instrument
        example = ""
        if same_rule.any():
            first_flag = flags[same_rule].iloc[0]
            day = "" if pd.isna(first_flag["date"]) else f"{first_flag['date']:%Y-%m-%d} "
            example = f"; first: {day}{first_flag['field']}: {first_flag['detail']}"
        where = f"{row.rule} | {row.source} | {row.instrument}"
        messages.append(f"{row.severity.upper()} {where}: {row.n_failed} failing row(s){example}")
    return messages


def build_freshness(raws: dict[str, pd.DataFrame | None], as_of: date) -> pd.DataFrame:
    """Each series' last observation against the last session a run can expect, in sessions late."""
    rows = []
    for series in CATALOG:
        table = raws.get(series.source)
        values = raw.series_values(table, series) if table is not None else pd.Series(dtype=float)
        expected = calendars.previous_session(series.calendar, as_of)
        last = values.index.max() if not values.empty else pd.NaT
        sessions_late = pd.NA
        if pd.notna(last):
            sessions_late = len(
                calendars.sessions(series.calendar or "weekdays", last + pd.Timedelta(days=1), expected)
            )
        rows.append(
            {
                "source": series.source,
                "instrument": series.instrument,
                "last_date": last,
                "expected_date": expected,
                "sessions_late": sessions_late,
            }
        )
    freshness = pd.DataFrame(rows).astype({"last_date": "datetime64[ns]", "sessions_late": "Int64"})
    is_late = freshness["sessions_late"].isna() | (freshness["sessions_late"] > 0)
    return freshness.assign(is_late=is_late.astype(bool))[FRESHNESS_COLUMNS]


def store(table: pd.DataFrame, path: Path, run_id: str) -> None:
    """Append a run to a results table; re-running the same run id replaces its rows."""
    if path.exists():
        previous = pd.read_parquet(path)
        table = pd.concat([previous[previous["run_id"] != run_id], table], ignore_index=True)
    files.write_parquet(table, path)


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Run the data quality gate on the latest raw files.")
    parser.add_argument("--fail-on", choices=["critical", "warning", "none"], default="critical")
    parser.add_argument("--as-of", type=date.fromisoformat, default=now.astimezone(config.PARIS).date())
    parser.add_argument("--run-id", default=os.environ.get("BUILD_TAG") or f"{now:%Y%m%dT%H%M%SZ}")
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    parser.add_argument("--dq-dir", type=Path, default=config.DQ_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)

    raws = {}
    for source in SOURCES:
        raws[source], path = raw.read_latest(args.raw_dir, source)
        log.info("%s: %s", source, path or "no raw file")
    fact, flags = evaluate(raws, args.as_of, args.run_id)
    run = {"run_id": args.run_id, "run_at": pd.Timestamp(now)}  # run_at orders runs for the report
    store(fact.assign(**run), args.dq_dir / "fact_dq.parquet", args.run_id)
    store(flags, args.dq_dir / "dq_flags.parquet", args.run_id)
    freshness = build_freshness(raws, args.as_of).assign(**run, date=pd.Timestamp(args.as_of).as_unit("ns"))
    store(freshness, args.dq_dir / "dq_freshness.parquet", args.run_id)

    for source, results in fact.groupby("source", sort=False):
        failed = results[~results["passed"]]
        n_critical = int((failed["severity"] == CRITICAL).sum())
        n_warning = int((failed["severity"] == WARNING).sum())
        summary = f"{len(results)} checks, {n_critical} critical and {n_warning} warning rules failed"
        log.info("%s: %s, %d flagged rows", source, summary, failed["n_failed"].sum())
    messages = gate(fact, flags, args.fail_on)
    if messages:
        log.error("QUALITY GATE FAILED (run %s): the pipeline stops before the silver tables.", args.run_id)
        for message in messages:
            log.error("  %s", message)
        log.error("Details: %s", args.dq_dir / "dq_flags.parquet")
        return 1
    log.info("quality gate passed (run %s, blocking severity: %s)", args.run_id, args.fail_on)
    return 0


if __name__ == "__main__":
    sys.exit(main())
