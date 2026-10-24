"""Daily 1-day VaR 99% and Expected Shortfall 97.5% of the book with five methods, from 2012.

VaR and ES are positive losses in euros. A figure computed at the close of day t covers day t+1 and is
stored with t+1 as `for_date`; the last row covers the next reporting day, not yet in the data.
Historical simulation reads the last 250 book P&Ls. The parametric methods scale normal quantiles by a
1-day volatility forecast (EWMA, GARCH, and the champion of the model registry, GJR-GARCH until a
weekly promotion run replaces it). Filtered historical simulation rescales the last 500 returns, each
divided by its own GJR forecast, to tomorrow's forecast.
GARCH-type models are refitted at the start of every month from 2010 on all past data. Rebuilt at
every run.
"""

import argparse
import logging
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

from pipeline import calendars, config, db, registry, risk, vol_models
from pipeline.book import BOOK_NOTIONAL

log = logging.getLogger("var")

FORECAST_START = pd.Timestamp("2010-01-01")  # first monthly refit of the 1-day volatility forecasts
VAR_START = pd.Timestamp("2012-01-01")  # first for_date: FHS has 500 standardised returns by then
PNL_QUERY = text("SELECT date, pnl_eur FROM gold.fact_pnl")
VAR_COLUMNS = ["for_date", "method_id", "var_99_eur", "es_975_eur"]
CHAMPION_NAME = text(
    "UPDATE gold.dim_method SET name = :name, description = :description WHERE method_id = 'param_champion'"
)


def book_pnl(pnl: pd.DataFrame) -> pd.Series:
    """Daily P&L of the book in euros."""
    return pnl.assign(date=pd.to_datetime(pnl["date"])).groupby("date")["pnl_eur"].sum()


def one_day_variances(returns: pd.Series) -> dict[str, pd.Series]:
    """1-day variance forecasts of the book return made at each close, by method."""
    months = vol_models.test_months(returns.index, start=FORECAST_START)
    return {
        "ewma": risk.ewma_variance(returns),
        "garch": vol_models.garch_forecasts(returns, months, asymmetric=False, horizon=1),
        "gjr": vol_models.garch_forecasts(returns, months, asymmetric=True, horizon=1),
    }


def next_reporting_day(day: pd.Timestamp) -> pd.Timestamp:
    return calendars.reporting_days(day + pd.Timedelta(days=1), day + pd.Timedelta(days=10))[0]


def to_for_date(estimates: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Re-date estimates made at the close of t to the day they cover, t+1."""
    following = pd.Series(dates[1:].append(pd.DatetimeIndex([next_reporting_day(dates[-1])])), index=dates)
    return estimates.set_axis(following.reindex(estimates.index).to_numpy())


def build_fact_var(
    pnl: pd.Series, variances: dict[str, pd.Series], champion: str = registry.DEFAULT_CHAMPION
) -> pd.DataFrame:
    returns = pnl / BOOK_NOTIONAL * 100
    methods = {
        "hs": risk.historical(pnl),
        "param_ewma": risk.parametric(variances["ewma"], BOOK_NOTIONAL),
        "param_garch": risk.parametric(variances["garch"], BOOK_NOTIONAL),
        "param_champion": risk.parametric(variances[champion], BOOK_NOTIONAL),
        "fhs": risk.filtered_historical(returns, variances["gjr"], BOOK_NOTIONAL),
    }
    frames = []
    for method_id, estimates in methods.items():
        dated = to_for_date(estimates, pnl.index)
        dated = dated[dated.index >= VAR_START]
        frames.append(
            pd.DataFrame(
                {
                    "for_date": dated.index,
                    "method_id": method_id,
                    "var_99_eur": dated["var"].to_numpy(),
                    "es_975_eur": dated["es"].to_numpy(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)[VAR_COLUMNS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily VaR and ES of the book with five methods.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        pnl = book_pnl(pd.read_sql(PNL_QUERY, conn))
    variances = one_day_variances(pnl / BOOK_NOTIONAL * 100)
    champion = registry.champion()
    fact_var = build_fact_var(pnl, variances, champion)
    with engine.begin() as conn:
        db.run_sql_file(conn, "var.sql")
        db.insert(conn, "gold", "fact_var", fact_var)
        conn.execute(
            CHAMPION_NAME,
            {
                "name": f"Parametric ({registry.SHORT_NAMES[champion]})",
                "description": f"Normal quantile, {registry.LONG_NAMES[champion]} volatility (the registry's champion)",
            },
        )
    log.info("parametric champion: %s", champion)

    first, last = f"{fact_var['for_date'].min():%Y-%m-%d}", f"{fact_var['for_date'].max():%Y-%m-%d}"
    log.info("gold.fact_var: %d rows, %s to %s", len(fact_var), first, last)
    latest = fact_var[fact_var["for_date"] == fact_var["for_date"].max()].set_index("method_id")
    for method_id, row in latest.iterrows():
        log.info(
            "%s for %s: VaR %s EUR, ES %s EUR",
            method_id,
            last,
            f"{row.var_99_eur:,.0f}",
            f"{row.es_975_eur:,.0f}",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
