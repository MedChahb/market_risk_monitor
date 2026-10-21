"""Data quality gate for the raw tables.

Runs the rules on the latest raw file of each source and stores the results in data/dq/:
fact_dq (one row per run, instrument and rule) and dq_flags (one row per flagged observation).
Exits with code 1 when a rule of the blocking severity fails, so bad data never reaches silver.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pandera.pandas as pa

from pipeline.catalog import CATALOG, FIELDS, SOURCES, Series, by_source, get, main_field

log = logging.getLogger("quality")

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DQ_DIR = ROOT / "data" / "dq"
PARIS = ZoneInfo("Europe/Paris")

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


def _is_utc(s: pd.Series) -> bool:
    return isinstance(s.dtype, pd.DatetimeTZDtype) and str(s.dtype.tz) == "UTC"


RAW_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column("datetime64[ns]"),
        "instrument": pa.Column(str, pa.Check.isin([s.instrument for s in CATALOG])),
        "field": pa.Column(str, pa.Check.isin(sorted({f for fields in FIELDS.values() for f in fields}))),
        "value": pa.Column(float, pa.Check(np.isfinite, error="finite")),
        "source": pa.Column(str, pa.Check.isin(SOURCES)),
        "downloaded_at": pa.Column(checks=pa.Check(_is_utc, error="UTC timestamp")),
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


# --- Calendars ---------------------------------------------------------------------------------


@lru_cache
def exchange_calendar(code: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(code, start="2005-01-03")


def sessions(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if code == "weekdays":
        return pd.bdate_range(start, end)
    cal = exchange_calendar(code)
    return cal.sessions_in_range(
        max(pd.Timestamp(start), cal.first_session), min(pd.Timestamp(end), cal.last_session)
    )


def previous_session(code: str | None, as_of: date) -> pd.Timestamp:
    """Last session strictly before the as-of date: the most recent close we expect to have."""
    end = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    return sessions(code or "weekdays", end - pd.Timedelta(days=14), end)[-1]


# --- Rules -------------------------------------------------------------------------------------


def no_flags() -> pd.DataFrame:
    return pd.DataFrame(
        {
            c: pd.Series(dtype=t)
            for c, t in zip(FLAG_COLUMNS, ["datetime64[ns]", str, str, float, str], strict=True)
        }
    )


def flag_rows(rows: pd.DataFrame, detail: str) -> pd.DataFrame:
    return rows.assign(detail=detail)[FLAG_COLUMNS]


def check_schema(raw: pd.DataFrame) -> pd.DataFrame:
    try:
        RAW_SCHEMA.validate(raw, lazy=True)
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
    return no_flags()


def check_duplicates(raw: pd.DataFrame) -> pd.DataFrame:
    dupes = raw[raw.duplicated(["date", "instrument", "field"], keep=False)]
    return flag_rows(dupes, "several rows share this (date, instrument, field)")


def check_non_positive(raw: pd.DataFrame) -> pd.DataFrame:
    prices = raw[raw["field"] != "volume"]
    return flag_rows(prices[prices["value"] <= 0], "price is zero or negative")


def check_yield_range(raw: pd.DataFrame) -> pd.DataFrame:
    low, high = YIELD_RANGE
    out = raw[(raw["value"] < low) | (raw["value"] > high)]
    return flag_rows(out, f"yield outside {low}% to {high}%")


def series_values(raw: pd.DataFrame, series: Series) -> pd.Series:
    rows = raw[(raw["instrument"] == series.instrument) & (raw["field"] == main_field(series))]
    rows = rows.drop_duplicates("date", keep="last")  # duplicates are reported by duplicate_key
    return rows.set_index("date")["value"].sort_index()


def as_flags(values: pd.Series, series: Series, detail: str | list[str]) -> pd.DataFrame:
    frame = values.rename("value").rename_axis("date").reset_index()
    return frame.assign(instrument=series.instrument, field=main_field(series), detail=detail)[FLAG_COLUMNS]


def check_missing_days(s: pd.Series, series: Series) -> pd.DataFrame:
    missing = sessions(series.calendar, s.index.min(), s.index.max()).difference(s.index)
    return as_flags(pd.Series(np.nan, index=missing), series, f"no data on a {series.calendar} session")


def check_stale(s: pd.Series, series: Series) -> pd.DataFrame:
    same = s.eq(s.shift())
    run = same.groupby((~same).cumsum()).cumsum() + 1  # length of the current run of equal values
    stale = run[run >= STALE_DAYS]
    return as_flags(s[stale.index], series, [f"same value {n} days in a row" for n in stale.astype(int)])


def check_large_move(s: pd.Series, series: Series) -> pd.DataFrame:
    move = s.pct_change()
    big = move[move.abs() > MAX_DAILY_MOVE]
    return as_flags(s[big.index], series, [f"{m:+.1%} vs previous value" for m in big])


def check_late(s: pd.Series, series: Series, as_of: date) -> pd.DataFrame:
    expected = previous_session(series.calendar, as_of)
    if s.empty:
        return as_flags(pd.Series([np.nan], index=[pd.Timestamp(as_of)]), series, "no data for this series")
    if s.index.max() >= expected:
        return no_flags()
    detail = f"last date {s.index.max():%Y-%m-%d}, expected {expected:%Y-%m-%d} or later"
    return as_flags(s.tail(1), series, detail)


def check_fx_cross_source(yahoo: pd.Series, ecb: pd.Series, series: Series) -> pd.DataFrame:
    both = pd.concat({"yahoo": yahoo, "ecb": ecb}, axis=1, join="inner")
    gap = both["yahoo"] / both["ecb"] - 1
    bad = both[gap.abs() > FX_TOLERANCE]
    detail = [
        f"Yahoo {y:.4f} vs ECB {e:.4f} ({g:+.2%})"
        for y, e, g in zip(bad["yahoo"], bad["ecb"], gap[bad.index], strict=True)
    ]
    return as_flags(bad["yahoo"], series, detail)


# --- Run ---------------------------------------------------------------------------------------


def evaluate(
    raws: dict[str, pd.DataFrame | None], as_of: date, run_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply every rule; return (fact_dq, dq_flags)."""
    results, flagged = [], []

    def record(source: str, instrument: str, rule: str, found: pd.DataFrame) -> None:
        results.append({"source": source, "instrument": instrument, "rule": rule, "n_failed": len(found)})
        if len(found):
            flagged.append(found.assign(source=source, rule=rule))

    valid: dict[str, pd.DataFrame] = {}
    for source in SOURCES:
        raw = raws.get(source)
        if raw is None:
            for series in by_source(source):
                record(
                    source, series.instrument, "late_data", check_late(pd.Series(dtype=float), series, as_of)
                )
            continue
        schema_flags = check_schema(raw)
        record(source, "*", "schema", schema_flags)
        if len(schema_flags):
            continue  # values cannot be trusted: the other rules are skipped for this source
        valid[source] = raw
        table_rules = {
            "duplicate_key": check_duplicates(raw),
            "non_positive_price": check_non_positive(raw),
            "yield_out_of_range": check_yield_range(raw),
        }
        for series in by_source(source):
            for rule, found in table_rules.items():
                if applies(rule, series):
                    record(source, series.instrument, rule, found[found["instrument"] == series.instrument])
            s = series_values(raw, series)
            record(source, series.instrument, "late_data", check_late(s, series, as_of))
            if s.empty:
                continue
            for rule, check in [
                ("missing_trading_day", check_missing_days),
                ("stale_value", check_stale),
                ("large_move", check_large_move),
            ]:
                if applies(rule, series):
                    record(source, series.instrument, rule, check(s, series))

    if "yahoo" in valid and "ecb" in valid:
        yahoo_fx, ecb_fx = get("EURUSD_YAHOO"), get("EURUSD")
        found = check_fx_cross_source(
            series_values(valid["yahoo"], yahoo_fx), series_values(valid["ecb"], ecb_fx), yahoo_fx
        )
        record("yahoo", yahoo_fx.instrument, "fx_cross_source", found)

    fact = pd.DataFrame(results)
    fact = fact.assign(
        run_id=run_id,
        date=pd.Timestamp(as_of).as_unit("ns"),
        severity=fact["rule"].map(RULES),
        passed=fact["n_failed"] == 0,
    )[FACT_DQ_COLUMNS]
    flags = pd.concat(flagged, ignore_index=True) if flagged else no_flags().assign(source=None, rule=None)
    flags = flags.assign(
        run_id=run_id,
        date=pd.to_datetime(flags["date"]).astype("datetime64[ns]"),
        severity=flags["rule"].map(RULES),
    )[DQ_FLAGS_COLUMNS]
    return fact, flags


def gate(fact: pd.DataFrame, flags: pd.DataFrame, fail_on: str) -> list[str]:
    """Readable messages for the failed rules of a blocking severity (empty list: the gate passes)."""
    blocking = {"critical": {CRITICAL}, "warning": {CRITICAL, WARNING}, "none": set()}[fail_on]
    messages = []
    for row in fact[~fact["passed"] & fact["severity"].isin(blocking)].itertuples():
        example = flags[(flags["rule"] == row.rule) & (flags["source"] == row.source)]
        example = example[example["instrument"] == row.instrument].head(1)
        first = ""
        if len(example):
            e = example.iloc[0]
            day = "" if pd.isna(e["date"]) else f"{e['date']:%Y-%m-%d} "
            first = f"; first: {day}{e['field']}: {e['detail']}"
        messages.append(
            f"{row.severity.upper()} {row.rule} | {row.source} | {row.instrument}: {row.n_failed} failing row(s){first}"
        )
    return messages


def latest_raw(raw_dir: Path, source: str) -> tuple[pd.DataFrame | None, Path | None]:
    files = sorted((raw_dir / source).glob("*.parquet"))
    return (pd.read_parquet(files[-1]), files[-1]) if files else (None, None)


def store(table: pd.DataFrame, path: Path, run_id: str) -> None:
    """Append a run to a results table; re-running the same run id replaces its rows."""
    if path.exists():
        previous = pd.read_parquet(path)
        table = pd.concat([previous[previous["run_id"] != run_id], table], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    table.to_parquet(tmp, index=False)
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Run the data quality gate on the latest raw files.")
    parser.add_argument("--fail-on", choices=["critical", "warning", "none"], default="critical")
    parser.add_argument("--as-of", type=date.fromisoformat, default=now.astimezone(PARIS).date())
    parser.add_argument("--run-id", default=os.environ.get("BUILD_TAG") or f"{now:%Y%m%dT%H%M%SZ}")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--dq-dir", type=Path, default=DQ_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    raws = {}
    for source in SOURCES:
        raws[source], path = latest_raw(args.raw_dir, source)
        log.info("%s: %s", source, path or "no raw file")
    fact, flags = evaluate(raws, args.as_of, args.run_id)
    store(fact, args.dq_dir / "fact_dq.parquet", args.run_id)
    store(flags, args.dq_dir / "dq_flags.parquet", args.run_id)

    for source, part in fact.groupby("source", sort=False):
        failed = part[~part["passed"]]
        log.info(
            "%s: %d checks, %d critical and %d warning rules failed, %d flagged rows",
            source, len(part), (failed["severity"] == CRITICAL).sum(), (failed["severity"] == WARNING).sum(),
            failed["n_failed"].sum(),
        )  # fmt: skip
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
