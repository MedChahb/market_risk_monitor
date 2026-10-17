"""Backtest of the daily VaR 99%: exceptions, Kupiec, Christoffersen and the Basel traffic light.

An exception is a day whose book loss exceeds the VaR computed at the previous close. The tests run
per method on the whole period and on 2020 and 2022; the count over the last 250 days gives the Basel
traffic-light zone. Rebuilt at every run, after the VaR stage.
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy import stats
from sqlalchemy import text

from pipeline import config, db
from pipeline.var import VAR_LEVEL

log = logging.getLogger("backtest")

EXCEPTION_RATE = 1 - VAR_LEVEL
TRAFFIC_WINDOW = 250  # days in the Basel traffic-light count
YELLOW, RED = 5, 10  # exceptions in 250 days that start the yellow and red zones
STRESS_YEARS = (2020, 2022)  # tested on their own as well as over the whole period
VAR_QUERY = text("SELECT for_date, method_id, var_99_eur FROM gold.fact_var")
PNL_QUERY = text("SELECT date, SUM(pnl_eur) AS pnl_eur FROM gold.fact_pnl GROUP BY date")


def zone(n_exceptions: float) -> str:
    """Basel traffic-light zone of an exception count over 250 days."""
    return "red" if n_exceptions >= RED else "yellow" if n_exceptions >= YELLOW else "green"


def build_fact_backtest(fact_var: pd.DataFrame, pnl: pd.Series) -> pd.DataFrame:
    """One row per method and day with a realised P&L: the exception flag and the 250-day count."""
    daily = fact_var.assign(pnl_eur=fact_var["for_date"].map(pnl)).dropna(subset=["pnl_eur"])
    daily = daily.sort_values(["method_id", "for_date"]).assign(
        is_exception=lambda d: d["pnl_eur"] < -d["var_99_eur"]
    )
    rolling = daily.groupby("method_id")["is_exception"].transform(
        lambda flags: flags.astype(int).rolling(TRAFFIC_WINDOW).sum()
    )
    daily = daily.assign(exceptions_250d=rolling.astype("Int64"))
    daily["zone"] = daily["exceptions_250d"].map(lambda count: zone(count) if pd.notna(count) else None)
    return daily.reset_index(drop=True)


def log_likelihood(n_hits: int, n_misses: int, probability: float) -> float:
    """Bernoulli log-likelihood, with 0 x log(0) = 0."""
    hits = n_hits * np.log(probability) if n_hits else 0.0
    misses = n_misses * np.log(1 - probability) if n_misses else 0.0
    return hits + misses


def kupiec(exceptions: np.ndarray, rate: float = EXCEPTION_RATE) -> tuple[float, float]:
    """Proportion-of-failures likelihood ratio and p-value (chi-squared, 1 degree of freedom)."""
    n, x = len(exceptions), int(exceptions.sum())
    ratio = -2 * (log_likelihood(x, n - x, rate) - log_likelihood(x, n - x, x / n))
    return ratio, stats.chi2.sf(ratio, df=1)


def christoffersen(exceptions: np.ndarray) -> tuple[float, float]:
    """Independence likelihood ratio and p-value: is an exception more likely the day after another?"""
    previous, current = exceptions[:-1].astype(bool), exceptions[1:].astype(bool)
    n01, n00 = int((~previous & current).sum()), int((~previous & ~current).sum())
    n11, n10 = int((previous & current).sum()), int((previous & ~current).sum())
    if n01 + n11 == 0:
        return 0.0, 1.0  # no exception after the first day: nothing to cluster
    after_calm, after_exception = n01 / (n00 + n01), n11 / (n10 + n11) if n10 + n11 else 0.0
    overall = (n01 + n11) / (n00 + n01 + n10 + n11)
    restricted = log_likelihood(n01 + n11, n00 + n10, overall)
    unrestricted = log_likelihood(n01, n00, after_calm) + log_likelihood(n11, n10, after_exception)
    ratio = -2 * (restricted - unrestricted)
    return ratio, stats.chi2.sf(ratio, df=1)


def summary(fact_backtest: pd.DataFrame) -> pd.DataFrame:
    """Per method and period: exceptions, the two tests, their joint (conditional coverage) test, zones."""
    rows = []
    for method_id, group in fact_backtest.groupby("method_id"):
        whole = f"{group['for_date'].min().year}-{group['for_date'].max().year}"
        periods = {
            whole: group,
            **{str(year): group[group["for_date"].dt.year == year] for year in STRESS_YEARS},
        }
        for period, part in periods.items():
            flags = part["is_exception"].to_numpy()
            kupiec_ratio, kupiec_p = kupiec(flags)
            independence_ratio, independence_p = christoffersen(flags)
            counts = part["exceptions_250d"].dropna()
            rows.append(
                {
                    "method_id": method_id,
                    "period": period,
                    "n_days": len(flags),
                    "n_exceptions": int(flags.sum()),
                    "expected_exceptions": len(flags) * EXCEPTION_RATE,
                    "kupiec_p": kupiec_p,
                    "christoffersen_p": independence_p,
                    "conditional_coverage_p": stats.chi2.sf(kupiec_ratio + independence_ratio, df=2),
                    "worst_zone": zone(counts.max()) if len(counts) else None,
                    "zone_at_end": zone(counts.iloc[-1]) if len(counts) else None,
                }
            )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the daily VaR of the book.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        fact_var = pd.read_sql(VAR_QUERY, conn, parse_dates=["for_date"])
        pnl = pd.read_sql(PNL_QUERY, conn, parse_dates=["date"]).set_index("date")["pnl_eur"]
    fact_backtest = build_fact_backtest(fact_var, pnl)
    tests = summary(fact_backtest)
    with engine.begin() as conn:
        db.run_sql_file(conn, "backtest.sql")
        db.insert(conn, "gold", "fact_backtest", fact_backtest)
        db.insert(conn, "gold", "fact_backtest_summary", tests)

    log.info(
        "gold.fact_backtest: %d rows; gold.fact_backtest_summary: %d rows", len(fact_backtest), len(tests)
    )
    for row in tests[tests["period"].str.contains("-")].itertuples():
        log.info(
            "%-15s %3d exceptions (expected %.0f), Kupiec p %.3f, Christoffersen p %.3f, worst zone %s",
            row.method_id,
            row.n_exceptions,
            row.expected_exceptions,
            row.kupiec_p,
            row.christoffersen_p,
            row.worst_zone,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
