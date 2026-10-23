# Pre-trade cost of an order

**Purpose.** Estimate, before trading, what an order of a given share of the next session's volume costs in basis points, for the ten CAC 40 stocks ([`notebooks/05_execution.ipynb`](../../notebooks/05_execution.ipynb); `pipeline/costs.py`).

**Data.** Daily high, low and close (Corwin-Schultz spread) and dividend-adjusted closes (EWMA volatility) since 2008.

**Method.** cost = spread / 2 + Y × σ × √(participation). The spread is the 63-session mean of the signed two-day Corwin and Schultz (2012) estimates, floored at zero; σ is the EWMA daily volatility forecast; Y = 1, the upper end of the 0.5 to 1 range reported for stocks and futures (Tóth, Eisler and Bouchaud, 2016). Every figure for a session uses data up to the previous close. Costs are stored for 1%, 5%, 10% and 20% of volume; the report computes any size with the same formula in DAX, checked against Python (37.55 bp for TotalEnergies at 7% on 22 October 2026).

**Results.** On 22 October 2026, an order of 10% of the session's volume costs 35 to 60 bp depending on the stock; the same order in TotalEnergies cost about three times its median in March 2020.

**Limits.** Daily-price spread estimates are dominated by noise for stocks this liquid: since 2018, 39% to 43% of the daily estimates are negative, with a standard deviation of 101 to 181 bp, and clipping them before averaging would give 37 to 52 bp, which mainly measures that noise. The signed mean used here is 0 to 7 bp and is floored at zero on 27% to 58% of sessions: the spread term is small and uncertain. Y comes from published studies, not from executions: post-trade transaction cost analysis on real orders would calibrate it. The model is a one-session estimate and ignores the order's schedule within the day.

**Monitoring.** Spread and cost history on the Execution page; no automatic test, as there is no realised cost to compare with.
