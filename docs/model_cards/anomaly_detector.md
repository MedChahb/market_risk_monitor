# Market data anomaly detector

**Purpose.** Flag suspect daily closes of the fourteen Yahoo price series at ingestion, before they reach the P&L and the VaR ([`notebooks/07_anomalies.ipynb`](../../notebooks/07_anomalies.ipynb); `pipeline/anomalies.py`).

**Data.** Daily closes of the CAC 40, Euro Stoxx 50, S&P 500, gold and the ten stocks.

**Method.** Robust z-score of the daily log return against the previous 63 returns: (r − median) / (1.4826 × MAD). A *bad tick* when |z| ≥ 6, at least two thirds of the move reverses the next day and the other series' median robust z stays within ±3; a *level shift* when |z| ≥ 30 without reversal (the largest real value since 2008 is 18.8). Reported by the quality gate as the warning rule `suspect_tick`, next to the stale-value and missing-session rules.

**Validation.** 200 errors of each type injected into the real closes with a fixed seed (seed 2; settings chosen with seed 1 and the real data): spikes, frozen prices, decimal shifts, unadjusted splits, missing days, roll jumps. Recall per type, precision, and a false alarm check on the ten largest real moves.

**Results.** Rules and robust z-score together: recall 100% for frozen prices, decimal shifts and missing days, 95.5% for splits, 78.5% for spikes, 0% for roll jumps of 2% to 6%; precision 0.912; none of the ten largest real moves flagged; five flags on the real history since 2008. An Isolation Forest on the same inputs reaches a precision of 0.632 for a similar spike recall and flags all ten largest real moves, so it is kept as a benchmark only.

**Limits.** A bad tick is confirmed by the next close, one session late; roll jumps need the futures roll calendar or a second source; errors shared by several series of the same source would pass the cross-asset check.

**Monitoring.** `suspect_tick` flags in the Data quality grid and table; the evaluation table on the same page is rebuilt at every night run.
