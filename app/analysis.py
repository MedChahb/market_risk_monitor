"""Risk of a custom book for the public app: daily P&L, VaR and ES by method, backtest, stress tests.

The book holds constant notionals in the six positions of the reference book, revalued with each
position's daily EUR return, as in pipeline/book.py. VaR and ES use the formulas of pipeline/risk.py
with EWMA volatility, which needs no fitting; the reference book's GJR-GARCH figures come from the
nightly pipeline. A figure computed at the close of a day covers the next session.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline import risk

METHODS = {
    "hs": "Historical simulation",
    "param_ewma": "Parametric (EWMA)",
    "fhs_ewma": "Filtered historical simulation (EWMA)",
}


@dataclass(frozen=True)
class Scenario:
    name: str
    start: str
    end: str
    description: str


SCENARIOS = [
    Scenario(
        "Lehman Brothers",
        "2008-09-15",
        "2008-10-10",
        "From the bankruptcy filing to the end of the worst week",
    ),
    Scenario("August 2011", "2011-08-01", "2011-08-19", "US downgrade and euro area debt crisis"),
    Scenario(
        "Brexit vote", "2016-06-24", "2016-06-27", "The two sessions after the result, to the euro equity low"
    ),
    Scenario(
        "Covid crash", "2020-02-20", "2020-03-23", "From the equity high of 19 February to the S&P 500 low"
    ),
    Scenario(
        "2022 rate rise",
        "2022-01-03",
        "2022-09-29",
        "From the equity highs to the Euro Stoxx 50 low, yields rising",
    ),
]


def book_pnl(returns: pd.DataFrame, notionals: pd.Series) -> pd.Series:
    """Daily P&L in euros: each position's notional times its EUR return (decimal), summed."""
    return returns[notionals.index] @ notionals


def gross_notional(notionals: pd.Series) -> float:
    return float(notionals.abs().sum())


def var_estimates(pnl: pd.Series, notional: float) -> dict[str, pd.DataFrame]:
    """VaR and ES computed at each close, by method; the last row covers the next session."""
    returns = pnl / notional * 100
    variance = risk.ewma_variance(returns)
    return {
        "hs": risk.historical(pnl),
        "param_ewma": risk.parametric(variance, notional),
        "fhs_ewma": risk.filtered_historical(returns, variance, notional),
    }


def latest(estimates: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The VaR and ES of each method for the session after the last close."""
    rows = {METHODS[method]: table.iloc[-1] for method, table in estimates.items()}
    return pd.DataFrame(rows).T[["var", "es"]]


def covering_var(pnl: pd.Series, estimates: pd.DataFrame) -> pd.Series:
    """For each day with a P&L, the VaR computed at the previous close."""
    return estimates["var"].reindex(pnl.index).shift(1)


def backtest(pnl: pd.Series, estimates: dict[str, pd.DataFrame], start: str, end: str) -> pd.DataFrame:
    """Per method, over the days from start to end that every method covers: exceptions, the expected
    count, Kupiec's and Christoffersen's p-values and the traffic-light zone of the last 250 days."""
    covering = pd.DataFrame({method: covering_var(pnl, table) for method, table in estimates.items()})
    days = covering.loc[start:end].dropna().index
    rows = {}
    for method in estimates:
        flags = (pnl[days] < -covering.loc[days, method]).to_numpy()
        rows[METHODS[method]] = {
            "days": len(flags),
            "exceptions": int(flags.sum()),
            "expected": len(flags) * risk.EXCEPTION_RATE,
            "kupiec_p": risk.kupiec(flags)[1],
            "christoffersen_p": risk.christoffersen(flags)[1],
            "zone": risk.zone(flags[-risk.TRAFFIC_WINDOW :].sum())
            if len(flags) >= risk.TRAFFIC_WINDOW
            else None,
        }
    return pd.DataFrame(rows).T


def stress(returns: pd.DataFrame, notionals: pd.Series, var_99: float) -> pd.DataFrame:
    """Each scenario replayed on the book: sessions, cumulative P&L, worst day, and losses in VaRs."""
    rows = []
    for scenario in SCENARIOS:
        pnl = book_pnl(returns.loc[scenario.start : scenario.end], notionals)
        rows.append(
            {
                "scenario": scenario.name,
                "window": f"{pd.Timestamp(scenario.start):%d %b %Y} to {pd.Timestamp(scenario.end):%d %b %Y}",
                "sessions": len(pnl),
                "cumulative_pnl": pnl.sum(),
                "worst_day_pnl": pnl.min(),
                "worst_day": pnl.idxmin(),
                "worst_day_in_vars": -pnl.min() / var_99,
                "cumulative_in_vars": -pnl.sum() / var_99,
            }
        )
    return pd.DataFrame(rows)


def contributions(returns: pd.DataFrame, notionals: pd.Series, scenario: Scenario) -> pd.Series:
    """Cumulative P&L of each position over a scenario."""
    window = returns.loc[scenario.start : scenario.end, notionals.index]
    return (window * notionals).sum().sort_values()


def exception_days(pnl: pd.Series, estimates: pd.DataFrame) -> pd.Series:
    covering = covering_var(pnl, estimates)
    return pnl[(pnl < -covering) & covering.notna()]


def complete_returns(pnl_table: pd.DataFrame) -> pd.DataFrame:
    """Daily EUR returns by position from gold fact_pnl, on the days every position has one."""
    dated = pnl_table.assign(date=pd.to_datetime(pnl_table["date"]))
    return dated.pivot(index="date", columns="position_id", values="return_eur").dropna().astype(np.float64)
