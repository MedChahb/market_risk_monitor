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

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy import stats
from sqlalchemy import text

from pipeline import calendars, config, db, registry, vol_models
from pipeline.book import BOOK_NOTIONAL

log = logging.getLogger("var")

VAR_LEVEL = 0.99
ES_LEVEL = 0.975
HS_WINDOW = 250  # trading days, the regulatory standard
FHS_WINDOW = 500  # standardised returns, about two years
FORECAST_START = pd.Timestamp("2010-01-01")  # first monthly refit of the 1-day volatility forecasts
VAR_START = pd.Timestamp("2012-01-01")  # first for_date: FHS has 500 standardised returns by then
NORMAL_VAR = stats.norm.ppf(VAR_LEVEL)  # 2.326
NORMAL_ES = stats.norm.pdf(stats.norm.ppf(ES_LEVEL)) / (1 - ES_LEVEL)  # 2.338: mean of the tail beyond 1.96
PNL_QUERY = text("SELECT date, pnl_eur FROM gold.fact_pnl")
VAR_COLUMNS = ["for_date", "method_id", "var_99_eur", "es_975_eur"]
CHAMPION_NAME = text(
    "UPDATE gold.dim_method SET name = :name, description = :description WHERE method_id = 'param_champion'"
)


def book_pnl(pnl: pd.DataFrame) -> pd.Series:
    """Daily P&L of the book in euros."""
    return pnl.assign(date=pd.to_datetime(pnl["date"])).groupby("date")["pnl_eur"].sum()


def tail_risk(losses: np.ndarray) -> tuple[float, float]:
    """VaR 99% and ES 97.5% of a sample of P&Ls (or standardised returns), as positive losses."""
    var = -np.quantile(losses, 1 - VAR_LEVEL)
    threshold = np.quantile(losses, 1 - ES_LEVEL)
    return var, -losses[losses <= threshold].mean()


def historical(pnl: pd.Series) -> pd.DataFrame:
    """VaR and ES computed at each close from the last 250 P&Ls, that day included."""
    values = pnl.to_numpy()
    rows = [tail_risk(values[end - HS_WINDOW : end]) for end in range(HS_WINDOW, len(values) + 1)]
    return pd.DataFrame(rows, index=pnl.index[HS_WINDOW - 1 :], columns=["var", "es"])


def parametric(variance: pd.Series) -> pd.DataFrame:
    """Normal VaR and ES from a 1-day variance forecast of the book return, in percent squared."""
    volatility_eur = np.sqrt(variance) / 100 * BOOK_NOTIONAL
    return pd.DataFrame({"var": NORMAL_VAR * volatility_eur, "es": NORMAL_ES * volatility_eur})


def filtered_historical(returns: pd.Series, variance: pd.Series) -> pd.DataFrame:
    """FHS: the last 500 returns, each divided by the volatility forecast for its day, rescaled by the
    forecast for tomorrow. variance is indexed by forecast date: the value at t is the forecast for t+1."""
    standardised = (returns / np.sqrt(variance.shift(1))).dropna()
    rows = {}
    for date in variance.index:
        window = standardised.loc[:date].to_numpy()[-FHS_WINDOW:]
        if len(window) < FHS_WINDOW:
            continue
        var, es = tail_risk(window)
        scale = np.sqrt(variance.loc[date]) / 100 * BOOK_NOTIONAL
        rows[date] = (var * scale, es * scale)
    return pd.DataFrame.from_dict(rows, orient="index", columns=["var", "es"])


def one_day_variances(returns: pd.Series) -> dict[str, pd.Series]:
    """1-day variance forecasts of the book return made at each close, by method."""
    months = vol_models.test_months(returns.index, start=FORECAST_START)
    return {
        "ewma": vol_models.ewma_variance(returns),
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
        "hs": historical(pnl),
        "param_ewma": parametric(variances["ewma"]),
        "param_garch": parametric(variances["garch"]),
        "param_champion": parametric(variances[champion]),
        "fhs": filtered_historical(returns, variances["gjr"]),
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
