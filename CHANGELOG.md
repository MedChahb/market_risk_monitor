# Changelog

Changes to the Power BI report in `powerbi/`, newest first.

## Unreleased

- 2026-10-23: Production page: status, end and duration of the latest night run, rows in gold, failed runs and the VaR champion; scheduled runs with the stage reached and the failed quality rules; input drift (PSI) at the latest run; rolling volatility and volume forecast errors against their baselines; promotion decisions. 11 new measures and the four monitoring tables; the Read me page lists the page.
- 2026-10-21: Anomaly detector. The Data quality page shows the detector's precision and recall on injected errors in place of the failed-rules-per-run chart; suspect prices appear as the `suspect_tick` rule in the grid and the flagged values; the flagged values drop the severity column and the freshness table narrows; the Read me page defines a suspect tick.
- 2026-10-21: Market regimes. The Market page shows the probability of the calm, normal and stress regimes at each close (walk-forward HMM) below shorter index and volatility charts; the Models page adds the QLIKE of each model by regime for the selected series; 5 new measures and the regime tables; the Read me page defines the regimes.
- 2026-10-20: Execution page: next-session volume forecast against actual volume for ten CAC 40 stocks, the volume models' losses and Diebold-Mariano tests against the 20-day ADV, the cost of an order chosen with an order-size slider, the next session's cost curve and the cost history; 13 new measures, an order-size what-if parameter and four gold tables. The stocks stay out of the Market page and the volume models out of the Models page; the quality grid takes the full width for twenty series and the pass rate moves to the key figures; the Read me page lists the definitions on the right.

## v1.0 (2026-10-19)

- 2026-10-19: Risk page headline on the full width with the slicers below it, exact amounts in the key figures, no exception count before 2012; empty Diebold-Mariano p-values left uncoloured; wider quality grid for the eleven series; spacing on the Read me page; the GJR parametric method named as in the notebooks.
- 2026-10-19: Risk page (latest VaR and ES, 250-day exceptions and traffic light, daily P&L against the VaR, backtest of five methods, exceptions by year), Models page (forecast against realised volatility, QLIKE, Diebold-Mariano against HAR) and Read me page; 17 new measures; Risk is the landing page.
- 2026-10-16: Series that only feed the models (VIX, EUR AAA 2-year yield, US 10y-2y) are kept out of the Market snapshot, index and volatility charts and of the correlation views; the 2-year yield joins the rates chart; headlines rebuilt after the FRED download.
- 2026-10-15: Returns in the Market snapshot show their sign; the quality grid fits all nine rules; the Market subtitle gives the date of series that were a session late.
- 2026-10-15: First version of the report on the gold Parquet tables. Market page (snapshot table, rebased index on a log scale, 22-day volatility, rates), Correlation page (pairwise matrix, a pair by calendar year, last 250 days against the full history versus the AAA yield) and Data quality page (latest run figures, flags by rule and series, flagged values, freshness). Semantic model in TMDL with 26 measures; custom theme.
