# Changelog

Changes to the Power BI report in `powerbi/`, newest first.

## Unreleased

- 2026-10-15: Returns in the Market snapshot show their sign; the quality grid fits all nine rules; the Market subtitle gives the date of series that were a session late.
- 2026-10-15: First version of the report on the gold Parquet tables. Market page (snapshot table, rebased index on a log scale, 22-day volatility, rates), Correlation page (pairwise matrix, a pair by calendar year, last 250 days against the full history versus the AAA yield) and Data quality page (latest run figures, flags by rule and series, flagged values, freshness). Semantic model in TMDL with 26 measures; custom theme.
