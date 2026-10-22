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

from pipeline import calendars, config, db, quality, raw, reference
from pipeline.catalog import CATALOG, SOURCES, get

log = logging.getLogger("transform")

PRICE_LIKE = ("equity index", "commodity", "fx")
VOL_WINDOW = 22  # observed trading days, about one month
RANGE_FIELDS = ["open", "high", "low", "close"]
CORRELATION_WINDOW = 250  # reporting days, about one year
FACT_MARKET_COLUMNS = [
    "date",
    "instrument_id",
    "level",
    "index_100",
    "daily_return",
    "change_bp",
    "vol_22d",
    "vol_22d_bp",
    "drawdown",
    "is_filled",
    "fill_reason",
]


def build_silver(raws: dict[str, pd.DataFrame | None]) -> pd.DataFrame:
    """Align every series (except cross-checks) on the reporting days, carrying values forward."""
    observed = {}
    for series in CATALOG:
        table = raws.get(series.source)
        if series.role == "cross-check" or table is None:
            continue
        values = raw.series_values(table, series)
        if not values.empty:
            observed[series] = values
    first_day = min(values.index.min() for values in observed.values())
    last_day = max(values.index.max() for values in observed.values())
    days = calendars.reporting_days(first_day, last_day)

    frames = []
    for series, values in observed.items():
        within_history = (days >= values.index.min()) & (
            days <= values.index.max()
        )  # nothing past the last value
        span = days[within_history]
        aligned = values.reindex(span)
        is_filled = aligned.isna()
        market_open = span.isin(calendars.sessions(series.calendar or "weekdays", span.min(), span.max()))
        reason = np.where(market_open, "missing_in_source", "market_closed")
        frame = pd.DataFrame(
            {
                "date": span,
                "instrument_id": series.instrument,
                "value": aligned.ffill().to_numpy(),
                "is_filled": is_filled.to_numpy(),
                "fill_reason": np.where(is_filled, reason, None),
            }
        )
        frames.append(frame.dropna(subset=["value"]))  # a gap before the first value has nothing to carry
    silver = pd.concat(frames, ignore_index=True)
    return silver.sort_values(["date", "instrument_id"]).reset_index(drop=True)


def range_variance(prices: pd.DataFrame) -> pd.DataFrame:
    """Close-to-close daily variance in percent squared, estimated from open, high, low and close.

    Garman and Klass (1980) on the trading session plus the overnight gap from the previous close
    (Yang and Zhang, 2000). Where the prices contradict each other (high below the close, high equal
    to the low), the squared close-to-close log return is used instead.
    """
    log_high_low = np.log(prices["high"] / prices["low"])
    log_close_open = np.log(prices["close"] / prices["open"])
    overnight = np.log(prices["open"] / prices["close"].shift())
    estimate = overnight**2 + 0.5 * log_high_low**2 - (2 * np.log(2) - 1) * log_close_open**2
    squared_return = np.log(prices["close"] / prices["close"].shift()) ** 2
    body_top, body_bottom = prices[["open", "close"]].max(axis=1), prices[["open", "close"]].min(axis=1)
    consistent = (
        (prices["high"] > prices["low"]) & (prices["high"] >= body_top) & (prices["low"] <= body_bottom)
    )
    variance = estimate.where(consistent, squared_return).clip(lower=0) * 1e4
    return pd.DataFrame({"range_variance": variance, "is_fallback": ~consistent}).dropna()


def build_daily_range(yahoo: pd.DataFrame | None) -> pd.DataFrame:
    """Range-based variance of every Yahoo series in silver, on the days it was observed."""
    frames = []
    for series in CATALOG:
        if series.source != "yahoo" or series.role == "cross-check" or yahoo is None:
            continue
        estimate = range_variance(raw.series_fields(yahoo, series, RANGE_FIELDS).dropna())
        frames.append(estimate.rename_axis("date").reset_index().assign(instrument_id=series.instrument))
    columns = ["date", "instrument_id", "range_variance", "is_fallback"]
    return pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)


def build_dim_date(trading_days: pd.DatetimeIndex, as_of: date) -> pd.DataFrame:
    """Every calendar day of the covered years, with a trading-day index for rolling windows."""
    start = pd.Timestamp(trading_days[0].year, 1, 1)
    end = pd.Timestamp(max(trading_days[-1].year, as_of.year), 12, 31)
    days = pd.date_range(start, end, freq="D")
    is_trading = days.isin(trading_days)
    index = pd.Series(np.cumsum(is_trading), index=days, dtype="Int64")
    index[(days < trading_days[0]) | (days > trading_days[-1])] = pd.NA

    # A month ends on its last session, which for the current month may lie after the data.
    sessions = trading_days.union(calendars.reporting_days(trading_days[-1], end))
    month_ends = sessions.to_series().groupby(sessions.to_period("M")).max()
    return pd.DataFrame(
        {
            "date": days,
            "year": days.year,
            "quarter": days.quarter,
            "month": days.month,
            "month_name": days.strftime("%b"),
            "day_of_week": days.dayofweek + 1,
            "is_trading_day": is_trading,
            "is_xpar_session": days.isin(calendars.sessions("XPAR", start, end)),
            "is_xnys_session": days.isin(calendars.sessions("XNYS", start, end)),
            "trading_day_index": index.to_numpy(),
            "is_month_end": is_trading & days.isin(month_ends),
        }
    )


def build_dim_instrument() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": series.instrument,
                "name": series.name,
                "short_name": series.short_name,
                "asset_class": series.asset_class,
                "currency": series.currency,
                "unit": series.unit,
                "role": series.role,
                "source_id": series.source,
                "source_key": series.key,
                "calendar": series.calendar,
                "licence": series.licence,
                "publish_level": series.publish_level,
            }
            for series in CATALOG
        ]
    )


def rolling_volatility(moves: pd.Series, is_filled: pd.Series) -> pd.Series:
    """Annualised volatility of the last 22 observed moves; a filled day keeps the previous value."""
    observed = moves[~is_filled]
    volatility = observed.rolling(VOL_WINDOW).std() * np.sqrt(252)
    return volatility.reindex(moves.index).ffill()


def build_fact_market(silver: pd.DataFrame) -> pd.DataFrame:
    """Daily market facts; raw levels only where the licence allows publishing them."""
    frames = []
    for instrument, rows in silver.groupby("instrument_id", sort=False):
        series = get(instrument)
        values, is_filled = rows["value"], rows["is_filled"]
        missing = pd.Series(np.nan, index=rows.index)
        price_like = series.asset_class in PRICE_LIKE
        has_returns = price_like or series.asset_class == "volatility index"
        is_rate = series.asset_class == "rates"
        daily_return = values.pct_change() if has_returns else missing
        change_bp = values.diff() * 100 if is_rate else missing
        frames.append(
            rows[["date", "instrument_id", "is_filled", "fill_reason"]].assign(
                level=values if series.publish_level else missing,
                index_100=values / values.iloc[0] * 100 if price_like else missing,
                daily_return=daily_return,
                change_bp=change_bp,
                vol_22d=rolling_volatility(daily_return, is_filled) if has_returns else missing,
                vol_22d_bp=rolling_volatility(change_bp, is_filled) if is_rate else missing,
                drawdown=values / values.cummax() - 1 if price_like else missing,
            )
        )
    return pd.concat(frames, ignore_index=True)[FACT_MARKET_COLUMNS]


def daily_moves(fact_market: pd.DataFrame) -> pd.DataFrame:
    """One column per instrument: returns, or changes in bp for rates; empty on filled days."""
    moves = fact_market["daily_return"].fillna(fact_market["change_bp"]).where(~fact_market["is_filled"])
    return fact_market.assign(move=moves).pivot(index="date", columns="instrument_id", values="move")


def build_fact_correlation(fact_market: pd.DataFrame) -> pd.DataFrame:
    """Pairwise correlation of daily moves by calendar year, over the last 250 days and over the full history."""
    moves = daily_moves(fact_market)
    periods = [(str(year), moves.loc[str(year)]) for year in sorted(moves.index.year.unique())]
    periods += [(f"Last {CORRELATION_WINDOW} days", moves.tail(CORRELATION_WINDOW)), ("Full history", moves)]
    names = {series.instrument: series.short_name for series in CATALOG}
    frames = []
    for order, (period, window) in enumerate(periods):
        moved = window.notna().astype(int)
        correlation = window.corr(min_periods=VOL_WINDOW).rename_axis(
            index="instrument_a", columns="instrument_b"
        )
        n_days = (moved.T @ moved).rename_axis(index="instrument_a", columns="instrument_b")
        pairs = correlation.stack().rename("correlation").to_frame().join(n_days.stack().rename("n_days"))
        frames.append(pairs.reset_index().assign(period=period, period_order=order))
    table = pd.concat(frames, ignore_index=True)
    table = table.assign(name_a=table["instrument_a"].map(names), name_b=table["instrument_b"].map(names))
    columns = [
        "period",
        "period_order",
        "instrument_a",
        "name_a",
        "instrument_b",
        "name_b",
        "correlation",
        "n_days",
    ]
    return table[columns]


def build_gold(silver: pd.DataFrame, as_of: date) -> dict[str, pd.DataFrame]:
    trading_days = pd.DatetimeIndex(silver["date"].unique()).sort_values()
    fact_market = build_fact_market(silver)
    return {
        "dim_source": pd.DataFrame(reference.DATA_SOURCES),
        "dim_instrument": build_dim_instrument(),
        "dim_date": build_dim_date(trading_days, as_of),
        "dim_model": pd.DataFrame(reference.MODELS),
        "dim_method": pd.DataFrame(reference.METHODS),
        "dim_regime": pd.DataFrame(reference.REGIMES),
        "fact_market": fact_market,
        "fact_correlation": build_fact_correlation(fact_market),
    }


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Build silver and gold tables from the latest raw files.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=now.astimezone(config.PARIS).date())
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    raws = {source: raw.read_latest(args.raw_dir, source)[0] for source in SOURCES}
    fact, flags = quality.evaluate(raws, args.as_of, run_id="transform")
    messages = quality.gate(fact, flags, "critical")
    if messages:
        log.error("raw data failed a critical quality rule; silver and gold are left unchanged:")
        for message in messages:
            log.error("  %s", message)
        return 1

    silver = build_silver(raws)
    daily_range = build_daily_range(raws["yahoo"])
    gold = build_gold(silver, args.as_of)
    with db.engine().begin() as conn:  # one transaction: readers never see a half-built schema
        db.run_sql_file(conn, "storage.sql")
        db.insert(conn, "silver", "market", silver)
        db.insert(conn, "silver", "daily_range", daily_range)
        for table, frame in gold.items():
            db.insert(conn, "gold", table, frame)

    first, last = f"{silver['date'].min():%Y-%m-%d}", f"{silver['date'].max():%Y-%m-%d}"
    n_instruments, n_filled = silver["instrument_id"].nunique(), int(silver["is_filled"].sum())
    log.info(
        "silver.market: %d rows, %d instruments, %s to %s, %d filled values",
        len(silver),
        n_instruments,
        first,
        last,
        n_filled,
    )
    fallbacks = daily_range.groupby("instrument_id")["is_fallback"].sum().to_dict()
    log.info("silver.daily_range: %d rows; fallback days by instrument: %s", len(daily_range), fallbacks)
    for table, frame in gold.items():
        log.info("gold.%s: %d rows", table, len(frame))
    return 0


if __name__ == "__main__":
    sys.exit(main())
