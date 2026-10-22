# Changelog

Changes to the Power BI report in `powerbi/`, newest first.

## Unreleased

- 2026-10-22: Series that only feed the models (VIX, EUR AAA 2-year yield, US 10y-2y) are kept out of the Market snapshot, index and volatility charts and of the correlation views; the 2-year yield joins the rates chart; headlines rebuilt after the FRED download.
- 2026-10-22: Returns in the Market snapshot show their sign; the quality grid fits all nine rules; the Market subtitle gives the date of series that were a session late.
- 2026-10-22: First version of the report on the gold Parquet tables. Market page (snapshot table, rebased index on a log scale, 22-day volatility, rates), Correlation page (pairwise matrix, a pair by calendar year, last 250 days against the full history versus the AAA yield) and Data quality page (latest run figures, flags by rule and series, flagged values, freshness). Semantic model in TMDL with 26 measures; custom theme.
