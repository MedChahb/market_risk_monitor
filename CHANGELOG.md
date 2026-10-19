# Changelog

Changes to the Power BI report in `powerbi/`, newest first.

## Unreleased

- 2026-10-19: Risk page headline on the full width with the slicers below it, exact amounts in the key figures, no exception count before 2012; empty Diebold-Mariano p-values left uncoloured; wider quality grid for the eleven series; spacing on the Read me page; the GJR parametric method named as in the notebooks.
- 2026-10-19: Risk page (latest VaR and ES, 250-day exceptions and traffic light, daily P&L against the VaR, backtest of five methods, exceptions by year), Models page (forecast against realised volatility, QLIKE, Diebold-Mariano against HAR) and Read me page; 17 new measures; Risk is the landing page.
- 2026-10-16: Series that only feed the models (VIX, EUR AAA 2-year yield, US 10y-2y) are kept out of the Market snapshot, index and volatility charts and of the correlation views; the 2-year yield joins the rates chart; headlines rebuilt after the FRED download.
- 2026-10-15: Returns in the Market snapshot show their sign; the quality grid fits all nine rules; the Market subtitle gives the date of series that were a session late.
- 2026-10-15: First version of the report on the gold Parquet tables. Market page (snapshot table, rebased index on a log scale, 22-day volatility, rates), Correlation page (pairwise matrix, a pair by calendar year, last 250 days against the full history versus the AAA yield) and Data quality page (latest run figures, flags by rule and series, flagged values, freshness). Semantic model in TMDL with 26 measures; custom theme.
