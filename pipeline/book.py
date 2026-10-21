"""The fictional trading book and its daily hypothetical P&L in euros.

Notionals are held constant every day (daily rebalancing). USD positions are converted with the ECB
EUR/USD reference rate. The bond is a 10-year zero-coupon repriced from the euro area AAA 10-year
yield at constant maturity, so its P&L captures yield moves only (no carry, no roll-down).
"""

import argparse
import logging
import sys
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv

from pipeline import db

log = logging.getLogger("book")

BOND_MATURITY = 10  # years, held constant
FX_INSTRUMENT = "EURUSD"  # USD per EUR


@dataclass(frozen=True)
class Position:
    position_id: str
    name: str
    notional_eur: float
    instrument: str | None  # silver series that prices the position; None for cash
    currency: str
    kind: str  # equity | commodity | bond | cash


BOOK = (
    Position("CAC40", "CAC 40", 2_000_000, "CAC40", "EUR", "equity"),
    Position("SX5E", "Euro Stoxx 50", 2_000_000, "SX5E", "EUR", "equity"),
    Position("SPX", "S&P 500", 2_000_000, "SPX", "USD", "equity"),
    Position("GOLD", "Gold", 1_000_000, "GOLD", "USD", "commodity"),
    Position("EUR_ZC10Y", "10-year euro zero-coupon bond", 2_000_000, "EUR10Y_AAA", "EUR", "bond"),
    Position("USD_CASH", "USD cash", 1_000_000, None, "USD", "cash"),
)
BOOK_NOTIONAL = sum(p.notional_eur for p in BOOK)
PNL_COLUMNS = ["date", "position_id", "return_local", "return_fx", "return_eur", "pnl_eur", "pnl_fx_eur"]


def zero_coupon_price(yield_pct: pd.Series | float, maturity: float = BOND_MATURITY) -> pd.Series | float:
    return 100 / (1 + yield_pct / 100) ** maturity


def local_return(levels: pd.DataFrame, position: Position) -> pd.Series:
    """Daily return of a position in its own currency; levels has one column per silver instrument."""
    if position.kind == "cash":
        return pd.Series(0.0, index=levels.index)
    if position.kind == "bond":
        return zero_coupon_price(levels[position.instrument]).pct_change()
    return levels[position.instrument].pct_change()


def usd_eur_return(levels: pd.DataFrame) -> pd.Series:
    """Return of the dollar against the euro: USD/EUR is the inverse of EUR/USD."""
    eurusd = levels[FX_INSTRUMENT]
    return eurusd.shift(1) / eurusd - 1


def position_pnl(levels: pd.DataFrame) -> pd.DataFrame:
    """One row per day and position, on days when every position can be valued."""
    fx = usd_eur_return(levels)
    frames = []
    for p in BOOK:
        r_local = local_return(levels, p)
        r_fx = fx if p.currency == "USD" else pd.Series(0.0, index=levels.index)
        r_eur = (1 + r_local) * (1 + r_fx) - 1
        frames.append(
            pd.DataFrame(
                {
                    "date": levels.index,
                    "position_id": p.position_id,
                    "return_local": r_local.to_numpy(),
                    "return_fx": r_fx.to_numpy(),
                    "return_eur": r_eur.to_numpy(),
                    "pnl_eur": (p.notional_eur * r_eur).to_numpy(),
                    "pnl_fx_eur": (p.notional_eur * (1 + r_local) * r_fx).to_numpy(),  # FX part of the P&L
                }
            )
        )
    pnl = pd.concat(frames, ignore_index=True)
    complete = pnl.pivot(index="date", columns="position_id", values="return_eur").dropna().index
    return (
        pnl[pnl["date"].isin(complete)]
        .sort_values(["date", "position_id"])
        .reset_index(drop=True)[PNL_COLUMNS]
    )


def book_pnl(pnl: pd.DataFrame) -> pd.DataFrame:
    """Daily book P&L (sum of positions) and book return (P&L over the constant book notional)."""
    book = pnl.groupby("date")["pnl_eur"].sum().to_frame("pnl_eur")
    return book.assign(return_book=book["pnl_eur"] / BOOK_NOTIONAL)


def dim_position() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "position_id": p.position_id,
                "name": p.name,
                "notional_eur": p.notional_eur,
                "instrument_id": p.instrument,
                "currency": p.currency,
                "kind": p.kind,
            }
            for p in BOOK
        ]
    )


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Compute the book's daily P&L from silver and load it into gold."
    ).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        silver = pd.read_sql(
            "SELECT date, instrument_id, value FROM silver.market", conn, parse_dates=["date"]
        )
    levels = silver.pivot(index="date", columns="instrument_id", values="value").sort_index()
    pnl = position_pnl(levels)
    with engine.begin() as conn:
        db.run_sql_file(conn, "book.sql")
        db.insert(conn, "gold", "dim_position", dim_position())
        db.insert(conn, "gold", "fact_pnl", pnl)

    book = book_pnl(pnl)
    log.info(
        "gold.fact_pnl: %d rows, %d positions, %d days, %s to %s",
        len(pnl), pnl["position_id"].nunique(), len(book), f"{book.index.min():%Y-%m-%d}", f"{book.index.max():%Y-%m-%d}",
    )  # fmt: skip
    for day, row in book.nsmallest(5, "pnl_eur").iterrows():
        log.info(
            "worst day %s: %s EUR (%+.2f%%)",
            f"{day:%Y-%m-%d}",
            f"{row['pnl_eur']:+,.0f}",
            100 * row["return_book"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
