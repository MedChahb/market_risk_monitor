"""Pre-trade cost of an order in each stock of the execution universe: half the spread plus market impact.

The bid-ask spread is estimated from daily highs and lows (Corwin and Schultz, 2012) and averaged over a
quarter; the impact follows the square-root law, Y x daily volatility x sqrt(order size / daily volume),
with the stock's EWMA volatility. Every figure for a session uses data up to the previous close.
Rebuilt at every run, after the transform stage.
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

from pipeline import calendars, config, db
from pipeline.vol_models import ewma_variance

log = logging.getLogger("costs")

SPREAD_WINDOW = 63  # sessions: a daily estimate's noise (about 140 bp) is far larger than the spread
IMPACT_CONSTANT = 1.0  # Y: 0.5 to 1 for stocks and futures (Tóth, Eisler and Bouchaud, 2016); upper end
PARTICIPATIONS = (0.01, 0.05, 0.10, 0.20)  # order size as a share of the session's volume
CORWIN_SCHULTZ_K = 3 - 2 * np.sqrt(2)
BAR_QUERY = text("SELECT date, instrument_id, high, low, close, adj_close FROM silver.daily_bar")


def corwin_schultz(bars: pd.DataFrame) -> pd.Series:
    """Signed spread estimate from the highs and lows of each day and the day before, as a fraction of price.

    A day's high-low range reflects volatility and the spread; over two days the volatility part doubles
    while the spread does not. As in the paper, a gap between the previous close and the day's range is
    removed first, so an overnight move is not read as spread. Negative values are kept: averaging them
    with the positive ones keeps the noise from inflating the estimate.
    """
    previous_close = bars["close"].shift()
    gap = (bars["low"] - previous_close).clip(lower=0) + (bars["high"] - previous_close).clip(upper=0)
    high, low = bars["high"] - gap, bars["low"] - gap
    previous_high, previous_low = bars["high"].shift(), bars["low"].shift()
    beta = np.log(high / low) ** 2 + np.log(previous_high / previous_low) ** 2
    gamma = np.log(np.maximum(high, previous_high) / np.minimum(low, previous_low)) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / CORWIN_SCHULTZ_K - np.sqrt(gamma / CORWIN_SCHULTZ_K)
    return 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))


def impact_bp(volatility_bp: pd.Series | float, participation: float) -> pd.Series | float:
    """Square-root law: Y daily volatilities times the root of the order's share of the volume."""
    return IMPACT_CONSTANT * volatility_bp * np.sqrt(participation)


def build_liquidity(instrument: str, bars: pd.DataFrame) -> pd.DataFrame:
    """Spread and volatility for the session after each date, from data up to that date's close."""
    estimate_bp = corwin_schultz(bars) * 1e4
    returns = bars["adj_close"].pct_change().dropna() * 100
    liquidity = pd.DataFrame(
        {
            "spread_estimate_bp": estimate_bp,
            "spread_bp": estimate_bp.rolling(SPREAD_WINDOW).mean().clip(lower=0),
            "volatility_bp": np.sqrt(ewma_variance(returns)) * 100,
        },
        index=bars.index,
    ).dropna()
    next_session = calendars.following_sessions("XPAR", liquidity.index)
    return liquidity.reset_index(drop=True).assign(date=next_session, instrument_id=instrument)[
        ["date", "instrument_id", "spread_estimate_bp", "spread_bp", "volatility_bp"]
    ]


def build_fact_cost(liquidity: pd.DataFrame) -> pd.DataFrame:
    """Cost in basis points of an order of each participation, for every stock and session."""
    frames = [
        liquidity[["date", "instrument_id", "spread_bp"]].assign(
            participation=participation, impact_bp=impact_bp(liquidity["volatility_bp"], participation)
        )
        for participation in PARTICIPATIONS
    ]
    cost = pd.concat(frames, ignore_index=True)
    cost = cost.assign(cost_bp=cost["spread_bp"] / 2 + cost["impact_bp"])
    return cost[["date", "instrument_id", "participation", "spread_bp", "impact_bp", "cost_bp"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-trade cost estimates for the execution universe.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        bars = pd.read_sql(BAR_QUERY, conn, parse_dates=["date"])
    liquidity = pd.concat(
        [
            build_liquidity(instrument, rows.set_index("date").sort_index())
            for instrument, rows in bars.groupby("instrument_id")
        ],
        ignore_index=True,
    )
    fact_cost = build_fact_cost(liquidity)
    with engine.begin() as conn:
        db.run_sql_file(conn, "costs.sql")
        db.insert(conn, "gold", "fact_liquidity", liquidity)
        db.insert(conn, "gold", "fact_cost", fact_cost)

    latest = fact_cost[fact_cost["date"] == fact_cost["date"].max()]
    curve = latest.pivot(index="instrument_id", columns="participation", values="cost_bp")
    log.info("cost in bp for %s by participation:\n%s", f"{latest['date'].max():%Y-%m-%d}", curve.round(1))
    log.info("gold.fact_liquidity: %d rows; gold.fact_cost: %d rows", len(liquidity), len(fact_cost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
