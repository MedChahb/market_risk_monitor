"""Build the silver and gold tables from the latest raw files and load them into PostgreSQL.

Silver holds one value per instrument and reporting day (a day when Paris or New York trades); a day
without an observation carries the last value forward and is flagged. Gold is the star schema read
by the report: the dimensions and fact_market. Both schemas are rebuilt at every run, and the raw
files are re-checked first: data with a critical quality failure never reaches silver.
"""

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from pipeline import db, quality, reference
from pipeline.catalog import CATALOG, SOURCES, get

log = logging.getLogger("transform")

REPORTING_CALENDARS = ("XPAR", "XNYS")
PRICE_LIKE = ("equity index", "commodity", "fx")


def reporting_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Days when at least one of the book's markets (Paris, New York) is open."""
    days = pd.DatetimeIndex([])
    for code in REPORTING_CALENDARS:
        days = days.union(quality.sessions(code, start, end))
    return days


def build_silver(raws: dict[str, pd.DataFrame | None]) -> pd.DataFrame:
    """Align every series (except cross-checks) on the reporting calendar, carrying values forward."""
    observed = {}
    for series in CATALOG:
        raw = raws.get(series.source)
        if series.role == "cross-check" or raw is None:
            continue
        values = quality.series_values(raw, series)
        if not values.empty:
            observed[series] = values
    start = min(v.index.min() for v in observed.values())
    end = max(v.index.max() for v in observed.values())
    days = reporting_days(start, end)

    frames = []
    for series, values in observed.items():
        span = days[
            (days >= values.index.min()) & (days <= values.index.max())
        ]  # no fill past the last value
        aligned = values.reindex(span)
        filled = aligned.isna()
        open_days = quality.sessions(series.calendar or "weekdays", span.min(), span.max())
        reason = np.where(span.isin(open_days), "missing_in_source", "market_closed")
        frame = pd.DataFrame(
            {
                "date": span,
                "instrument_id": series.instrument,
                "value": aligned.ffill().to_numpy(),
                "is_filled": filled.to_numpy(),
                "fill_reason": np.where(filled, reason, None),
            }
        )
        frames.append(frame.dropna(subset=["value"]))  # a leading gap has nothing to carry
    return pd.concat(frames, ignore_index=True).sort_values(["date", "instrument_id"]).reset_index(drop=True)


def build_dim_date(trading_days: pd.DatetimeIndex, as_of: date) -> pd.DataFrame:
    """Every calendar day of the covered years, with a trading-day index for rolling windows."""
    start = pd.Timestamp(trading_days[0].year, 1, 1)
    end = pd.Timestamp(max(trading_days[-1].year, as_of.year), 12, 31)
    days = pd.date_range(start, end, freq="D")
    is_trading = days.isin(trading_days)
    index = pd.Series(np.cumsum(is_trading), index=days, dtype="Int64")
    index[(days < trading_days[0]) | (days > trading_days[-1])] = pd.NA

    future = reporting_days(trading_days[-1], end)  # month end needs the next session, even after the data
    sessions = trading_days.union(future)
    next_session = pd.Series(sessions[1:].append(pd.DatetimeIndex([pd.NaT])), index=sessions)
    month_end = sessions[((next_session.dt.month != sessions.month) & next_session.notna()).to_numpy()]
    return pd.DataFrame(
        {
            "date": days,
            "year": days.year,
            "quarter": days.quarter,
            "month": days.month,
            "month_name": days.strftime("%b"),
            "day_of_week": days.dayofweek + 1,
            "is_trading_day": is_trading,
            "is_xpar_session": days.isin(quality.sessions("XPAR", start, end)),
            "is_xnys_session": days.isin(quality.sessions("XNYS", start, end)),
            "trading_day_index": index.to_numpy(),
            "is_month_end": is_trading & days.isin(month_end),
        }
    )


def build_dim_instrument() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": s.instrument,
                "name": s.name,
                "asset_class": s.asset_class,
                "currency": s.currency,
                "unit": s.unit,
                "role": s.role,
                "source_id": s.source,
                "source_key": s.key,
                "calendar": s.calendar,
                "licence": s.licence,
                "publish_level": s.publish_level,
            }
            for s in CATALOG
        ]
    )


def build_fact_market(silver: pd.DataFrame) -> pd.DataFrame:
    """Daily market facts; raw levels only where the licence allows publishing them."""
    frames = []
    for instrument, rows in silver.groupby("instrument_id", sort=False):
        series = get(instrument)
        v = rows["value"]
        nan = pd.Series(np.nan, index=rows.index)
        price_like = series.asset_class in PRICE_LIKE
        frames.append(
            rows[["date", "instrument_id", "is_filled", "fill_reason"]].assign(
                level=v if series.publish_level else nan,
                index_100=v / v.iloc[0] * 100 if price_like else nan,
                daily_return=v.pct_change()
                if price_like or series.asset_class == "volatility index"
                else nan,
                change_bp=v.diff() * 100 if series.asset_class == "rates" else nan,
            )
        )
    columns = [
        "date",
        "instrument_id",
        "level",
        "index_100",
        "daily_return",
        "change_bp",
        "is_filled",
        "fill_reason",
    ]
    return pd.concat(frames, ignore_index=True)[columns]


def build_gold(silver: pd.DataFrame, as_of: date) -> dict[str, pd.DataFrame]:
    trading_days = pd.DatetimeIndex(silver["date"].unique()).sort_values()
    return {
        "dim_source": pd.DataFrame(reference.DATA_SOURCES),
        "dim_instrument": build_dim_instrument(),
        "dim_date": build_dim_date(trading_days, as_of),
        "dim_model": pd.DataFrame(reference.MODELS),
        "dim_method": pd.DataFrame(reference.METHODS),
        "dim_regime": pd.DataFrame(reference.REGIMES),
        "fact_market": build_fact_market(silver),
    }


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Build silver and gold tables from the latest raw files.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=now.astimezone(quality.PARIS).date())
    parser.add_argument("--raw-dir", type=Path, default=quality.RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()

    raws = {source: quality.latest_raw(args.raw_dir, source)[0] for source in SOURCES}
    fact, flags = quality.evaluate(raws, args.as_of, run_id="transform")
    messages = quality.gate(fact, flags, "critical")
    if messages:
        log.error("raw data failed a critical quality rule; silver and gold are left unchanged:")
        for message in messages:
            log.error("  %s", message)
        return 1

    silver = build_silver(raws)
    gold = build_gold(silver, args.as_of)
    with db.engine().begin() as conn:  # one transaction: readers never see a half-built schema
        db.run_sql_file(conn, "storage.sql")
        db.insert(conn, "silver", "market", silver)
        for table, frame in gold.items():
            db.insert(conn, "gold", table, frame)
    log.info(
        "silver.market: %d rows, %d instruments, %s to %s, %d filled values",
        len(silver), silver["instrument_id"].nunique(), f"{silver['date'].min():%Y-%m-%d}",
        f"{silver['date'].max():%Y-%m-%d}", silver["is_filled"].sum(),
    )  # fmt: skip
    for table, frame in gold.items():
        log.info("gold.%s: %d rows", table, len(frame))
    return 0


if __name__ == "__main__":
    sys.exit(main())
