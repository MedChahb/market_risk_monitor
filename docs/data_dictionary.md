# Data dictionary

Owner of every dataset: the project maintainer. Series metadata is defined once in [`pipeline/catalog.py`](../pipeline/catalog.py); quality rules in [`pipeline/quality.py`](../pipeline/quality.py).

## Series

| Instrument | Name | Source | Identifier | Asset class | Unit | Calendar | Licence and handling |
|---|---|---|---|---|---|---|---|
| `CAC40` | CAC 40 | Yahoo Finance | `^FCHI` | Equity index (EUR) | Index points | XPAR | Yahoo terms: personal use; raw data not redistributed |
| `SX5E` | Euro Stoxx 50 | Yahoo Finance | `^STOXX50E` | Equity index (EUR) | Index points | XPAR | Yahoo terms: personal use; raw data not redistributed |
| `SPX` | S&P 500 | Yahoo Finance | `^GSPC` | Equity index (USD) | Index points | XNYS | Yahoo terms: personal use; raw data not redistributed |
| `GOLD` | Gold front-month future (COMEX) | Yahoo Finance | `GC=F` | Commodity (USD) | USD per troy ounce | XNYS | Yahoo terms: personal use; raw data not redistributed |
| `EURUSD_YAHOO` | EUR/USD, cross-check only | Yahoo Finance | `EURUSD=X` | FX | USD per EUR | Weekdays | Yahoo terms: personal use; raw data not redistributed |
| `EURUSD` | EUR/USD ECB reference rate | ECB Data Portal | `EXR` / `D.USD.EUR.SP00.A` | FX | USD per EUR | XPAR | ECB statistics: reuse with source acknowledgement |
| `EUR10Y_AAA` | Euro area AAA 10-year spot yield | ECB Data Portal | `YC` / `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y` | Rates | Percent per annum | XPAR | ECB statistics: reuse with source acknowledgement |
| `EUR2Y_AAA` | Euro area AAA 2-year spot yield (model input: euro curve slope) | ECB Data Portal | `YC` / `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y` | Rates | Percent per annum | XPAR | ECB statistics: reuse with source acknowledgement |
| `VIX` | Cboe Volatility Index | FRED | `VIXCLS` | Volatility index | Index points | XNYS | Cboe data via FRED; raw data not redistributed |
| `US10Y2Y` | US 10-year minus 2-year Treasury yield | FRED | `T10Y2Y` | Rates | Percentage points | None (US bond market) | US Treasury data via FRED; raw data not redistributed |

Conventions:

- **Dates** are trading dates in the market's local time zone, stored without a time zone. `downloaded_at` is in UTC.
- **Yahoo prices** are requested with `auto_adjust=False`. For price indices `close` equals `adj_close` on every row. `GC=F` is the front-month future: its series jumps when the contract rolls.
- **Live bars:** a Yahoo bar dated today is kept only after the local close plus a buffer (Paris 18:00, New York 16:30 for the S&P 500 and 17:30 for gold). Yahoo EUR/USD trades around the clock, so only bars up to the previous day are kept.
- **ECB EUR/USD** is the reference rate set around 14:15 CET on TARGET business days, which match the XPAR calendar exactly since 2008. It is the rate used to convert USD positions.
- **FRED** marks a day without a value with `"."`; such days are dropped at ingestion.
- **Calendars** come from `exchange_calendars`. `US10Y2Y` follows the US bond market calendar, which that library does not provide, so it has no completeness check.
- **Roles:** book risk factors (`CAC40`, `SX5E`, `SPX`, `GOLD`, `EURUSD`, `EUR10Y_AAA`), model inputs (`VIX`, `US10Y2Y`) and the cross-check `EURUSD_YAHOO`, used by the quality gate only.
- **Publication:** gold tables carry raw levels only where the licence allows redistribution (the two ECB series). Other price series are published as an index rebased to 100 and daily returns.

## Tables

### Raw: `data/raw/<source>/<download_date>.parquet`

One file per source and download day (Paris date), rewritten in full by each run. Not committed.

| Column | Type | Description |
|---|---|---|
| `date` | datetime64[ns] | Trading date of the observation |
| `instrument` | string | Instrument id from the catalog |
| `field` | string | Yahoo: `open`, `high`, `low`, `close`, `adj_close`, `volume`. ECB and FRED: `value` |
| `value` | float64 | Observation, in the instrument's unit |
| `source` | string | `yahoo`, `ecb` or `fred` |
| `downloaded_at` | datetime64[us, UTC] | Time of the download |

Key: (`date`, `instrument`, `field`).

### Silver: `silver.market` (PostgreSQL)

One value per instrument and reporting day, rebuilt from the latest raw files at every run, after the quality gate. Not exported.

| Column | Type | Description |
|---|---|---|
| `date` | date | Reporting day: a session of Paris (XPAR) or New York (XNYS) |
| `instrument_id` | text | Instrument id (cross-check series excluded) |
| `value` | double | Level in the instrument's unit (close for Yahoo series) |
| `is_filled` | boolean | True when the day had no observation and the previous value was carried forward |
| `fill_reason` | text | `market_closed` (holiday of the instrument's market) or `missing_in_source` (open session, no data); empty when not filled |

Key: (`date`, `instrument_id`). Values are carried forward only between an instrument's first and last observation; a filled day has a zero return and the move is captured on the next observed day.

### Silver: `silver.daily_range` (PostgreSQL)

Range-based daily variance of the Yahoo series of silver (CAC 40, Euro Stoxx 50, S&P 500, gold), on the days they were observed. Not exported: it is derived from Yahoo prices that may not be redistributed.

| Column | Type | Description |
|---|---|---|
| `date` | date | Observed session |
| `instrument_id` | text | Instrument id |
| `range_variance` | double | Close-to-close variance in percent squared: Garman and Klass (1980) on open, high, low and close, plus the squared overnight log gap from the previous close (Yang and Zhang, 2000) |
| `is_fallback` | boolean | True when the prices contradict each other (high not above low, or not containing open and close): the squared close-to-close log return is used instead |

Key: (`date`, `instrument_id`). Fallback days on 2026-10-22: gold 233 (front-month future), Euro Stoxx 50 7, CAC 40 and S&P 500 none.

### Gold: star schema (PostgreSQL `gold`, exported to `data/gold/<table>.parquet`)

The Parquet files are written from PostgreSQL, and the export fails if a file's row count differs from its table's. Dates are stored as Parquet `date32`.

**`dim_date`**: every calendar day of the covered years, so the report can mark it as a date table.

| Column | Type | Description |
|---|---|---|
| `date` | date | Key |
| `year`, `quarter`, `month`, `month_name`, `day_of_week` | int / text | Calendar attributes (`day_of_week`: 1 = Monday) |
| `is_trading_day` | boolean | Reporting day with data (Paris or New York open) |
| `is_xpar_session`, `is_xnys_session` | boolean | Session of each exchange |
| `trading_day_index` | int | Number of trading days up to and including this date (a weekend keeps Friday's value); empty outside the data range. Used for rolling windows such as the last 250 trading days |
| `is_month_end` | boolean | Last trading day of the month |

**`dim_instrument`**: one row per catalog series: `instrument_id` (key), `name`, `short_name` (label for charts and matrix headers), `asset_class`, `currency`, `unit`, `role`, `source_id` (to `dim_source`), `source_key`, `calendar`, `licence`, `publish_level`.

**`dim_source`**: `source_id` (key), `name`, `url`, `licence`.

**`dim_model`**, **`dim_method`**, **`dim_regime`**: reference lists of the volatility models, VaR methods and market regimes used by later stages (`*_id`, `name`, `description`).

**`fact_market`**: one row per instrument and reporting day.

| Column | Type | Description |
|---|---|---|
| `date` | date | To `dim_date` |
| `instrument_id` | text | To `dim_instrument` |
| `level` | double | Level in the instrument's unit, only where `publish_level` is true |
| `index_100` | double | Equities, gold and FX rebased to 100 on their first date |
| `daily_return` | double | Simple daily return: equities, gold, FX and VIX |
| `change_bp` | double | Daily change in basis points: rates |
| `vol_22d` | double | Annualised volatility (√252 scaling) of the last 22 observed daily returns; a filled day keeps the previous value |
| `vol_22d_bp` | double | Rates: annualised volatility of the last 22 observed daily changes, in basis points |
| `drawdown` | double | Equities, gold and FX: fall below the highest level since the first date (0 at a new high) |
| `is_filled`, `fill_reason` | boolean, text | As in silver |

Key: (`date`, `instrument_id`).

**`fact_correlation`**: correlation of daily moves (returns, or changes in bp for rates) between every pair of silver instruments, on days when both moved. One row per period and ordered pair, with the diagonal, so the report can draw a full matrix.

| Column | Type | Description |
|---|---|---|
| `period`, `period_order` | text, int | A calendar year, `Last 250 days` or `Full history`, and its sort key |
| `instrument_a`, `instrument_b` | text | To `dim_instrument` |
| `name_a`, `name_b` | text | Short instrument names, for display |
| `correlation` | double | Pearson correlation; empty below 22 common days |
| `n_days` | int | Days when both instruments moved |

Key: (`period`, `instrument_a`, `instrument_b`). The rate series' correlation is with yield changes: a positive value means the bond price moves the other way.

**`dim_position`**: the fictional 10 M€ book (defined in [`pipeline/book.py`](../pipeline/book.py)).

| `position_id` | Name | Notional (EUR) | Priced from | Currency | Kind |
|---|---|---|---|---|---|
| `CAC40` | CAC 40 | 2,000,000 | `CAC40` | EUR | equity |
| `SX5E` | Euro Stoxx 50 | 2,000,000 | `SX5E` | EUR | equity |
| `SPX` | S&P 500 | 2,000,000 | `SPX` | USD | equity |
| `GOLD` | Gold | 1,000,000 | `GOLD` | USD | commodity |
| `EUR_ZC10Y` | 10-year euro zero-coupon bond | 2,000,000 | `EUR10Y_AAA` | EUR | bond |
| `USD_CASH` | USD cash | 1,000,000 | none | USD | cash |

**`fact_pnl`**: daily hypothetical P&L, one row per day and position, on days when every position can be valued.

| Column | Type | Description |
|---|---|---|
| `date` | date | To `dim_date` |
| `position_id` | text | To `dim_position` |
| `return_local` | double | Return in the position's currency: price return; for the bond, the change of `100 × exp(−y × 10)` with the AAA 10-year spot yield `y`, continuously compounded as the ECB publishes it, at constant maturity; 0 for cash |
| `return_fx` | double | USD/EUR return (the inverse of the ECB EUR/USD rate) for USD positions, 0 otherwise |
| `return_eur` | double | `(1 + return_local) × (1 + return_fx) − 1` |
| `pnl_eur` | double | `notional_eur × return_eur` |
| `pnl_fx_eur` | double | Part of the P&L due to the dollar: `notional_eur × (1 + return_local) × return_fx` |

Key: (`date`, `position_id`). Notionals are constant (daily rebalancing). Book P&L = sum of `pnl_eur` per day; book return = book P&L / 10 M€. The P&L excludes trading, fees, carry and roll-down.

**`fact_forecast`**: out-of-sample volatility forecasts from 2018, written by [`pipeline/vol_models.py`](../pipeline/vol_models.py) to `data/forecasts/` and reloaded in full at every publish. Series: each position's EUR return and the book return, in percent.

| Column | Type | Description |
|---|---|---|
| `date` | date | Forecast made at this day's close; to `dim_date` |
| `series_id` | text | A `position_id` of `dim_position`, or `book` |
| `model_id` | text | To `dim_model`: `ewma`, `garch`, `har`, `xgboost`, `gru` |
| `forecast_var` | double | Forecast of the mean daily variance of the next 5 trading days, in percent squared (annualised volatility in percent: `sqrt(252 × forecast_var)`) |
| `realised_var` | double | The same quantity measured afterwards: mean squared return of the next 5 days; empty for the last 5 days |
| `inputs` | text | Features the model used (`returns` for EWMA and GARCH) |

Key: (`date`, `series_id`, `model_id`). Models are refitted at the start of each month on all past data; supervised models leave out the last 5 training rows, whose targets overlap the forecast month.

**`fact_var`**: daily 1-day VaR 99% and ES 97.5% of the book from 2012, rebuilt by [`pipeline/var.py`](../pipeline/var.py) at every run.

| Column | Type | Description |
|---|---|---|
| `for_date` | date | Day the figure covers; it was computed at the close of the previous trading day. The last row covers the next reporting day; to `dim_date` |
| `method_id` | text | To `dim_method`: `hs` (last 250 book P&Ls), `param_ewma`, `param_garch`, `param_champion` (normal quantiles times a 1-day EWMA, GARCH or GJR-GARCH volatility), `fhs` (500 returns standardised by GJR-GARCH, rescaled to tomorrow's forecast) |
| `var_99_eur` | double | 1-day VaR 99% in euros, as a positive loss |
| `es_975_eur` | double | 1-day ES 97.5% in euros, as a positive loss |

Key: (`for_date`, `method_id`). GARCH-type forecasts are refitted at the start of each month from 2010 on all past data. Normal multipliers: 2.326 (VaR 99%) and 2.338 (ES 97.5%).

### `fact_dq`: one row per run, instrument and rule

| Column | Type | Description |
|---|---|---|
| `run_id` | string | Run identifier (Jenkins `BUILD_TAG`, or a UTC timestamp) |
| `date` | datetime64[ns] | As-of date of the run (Paris) |
| `source` | string | Source checked |
| `instrument` | string | Instrument checked; `*` for source-level rules (schema) |
| `rule` | string | Rule name (see below) |
| `severity` | string | `critical` or `warning` |
| `passed` | bool | True when no row failed |
| `n_failed` | int64 | Number of failing rows |
| `run_at` | timestamp (UTC) | When the run started; empty for runs recorded before 2026-10-22 |

### `dq_flags`: one row per flagged observation

| Column | Type | Description |
|---|---|---|
| `run_id` | string | Run identifier |
| `date` | datetime64[ns] | Date of the flagged observation (empty for schema failures) |
| `source`, `instrument`, `field` | string | Where the failure is |
| `rule`, `severity` | string | Rule that failed and its severity |
| `value` | float64 | Flagged value (empty for a missing day). In `gold.fact_dq_flags` it is kept only for series whose licence allows publishing levels (the ECB series) |
| `detail` | string | Human-readable reason; it never repeats a level that may not be published |

### `dq_freshness`: one row per run and series

| Column | Type | Description |
|---|---|---|
| `run_id`, `run_at`, `date` | text, timestamp, date | Run identifier, start time (UTC) and as-of date |
| `source`, `instrument` | string | Series checked |
| `last_date` | datetime64[ns] | Last observation; empty when the source delivered nothing |
| `expected_date` | datetime64[ns] | Last session of the series' calendar before the as-of date |
| `sessions_late` | Int64 | Sessions between the two; empty when there is no data |
| `is_late` | bool | True when at least one session is missing, or no data at all |

The three tables are written to `data/dq/` by the quality gate (a re-run with the same `run_id` replaces that run's rows), then loaded into `gold.fact_dq`, `gold.fact_dq_flags` and `gold.fact_freshness` with an `is_latest_run` flag (the run with the most recent `run_at`), and exported with the other gold tables.

## Quality rules

A **critical** rule stops the pipeline before the silver tables (`python -m pipeline.quality --fail-on critical`). A **warning** is stored and reported, and the data is loaded.

| Rule | Severity | Applies to | Threshold | Rationale |
|---|---|---|---|---|
| `schema` | Critical | Every raw table | Columns, types, known instruments, fields and sources, finite values, UTC timestamp (pandera) | A malformed table makes every other check unreliable; the other rules are skipped for that source |
| `duplicate_key` | Critical | Every series | Unique (`date`, `instrument`, `field`) | A duplicate would double-count a day in returns and P&L |
| `non_positive_price` | Critical | Every series except rates | Price fields ≤ 0 | Prices and FX rates are strictly positive; rates can be negative |
| `yield_out_of_range` | Critical | `EUR10Y_AAA` | Outside −2% to 15% | Observed range since 2008 is −0.82% to 4.78%; the bounds catch unit or scaling errors |
| `missing_trading_day` | Warning | Series with a calendar | Session without data | Gaps can be real feed holes or calendar differences; they are documented, not deleted |
| `stale_value` | Warning | Every series | Same value 3 days in a row | A frozen feed repeats the last value |
| `large_move` | Warning | Equity indices, gold, FX | Daily change above 15% | The largest real move since 2008 is 12.4% (Euro Stoxx 50, 12 March 2020); real crashes must be kept |
| `late_data` | Warning | Every series | Last date before the previous session | Some sources publish the next morning; a late day is not an error |
| `fx_cross_source` | Warning | `EURUSD_YAHOO` vs `EURUSD` | Relative gap above 2% | The two sources fix at different times; 2% is about 3.6 daily standard deviations of EUR/USD (0.56%) |

## Known data issues (checked on 2026-10-21, FRED on 2026-10-22)

- **Yahoo EUR/USD, August 2008:** 8 observations are stored with day and month swapped. For example, the row dated 2008-01-08 (1.5571) matches the ECB rate of 2008-08-01 (1.5574). Most of August 2008 is therefore missing. Over the full history, 16 days differ from the ECB by more than 2%: the swapped rows, and days with large moves between the two fixing times (for example 2016-06-24, the day after the Brexit vote, and 2024-11-06). The ECB series is the one used for conversion.
- **Yahoo Euro Stoxx 50:** 98 XPAR sessions missing since 2008, about five a year, mostly Swiss holidays (1 August, Ascension, Whit Monday) and US holidays. The index is calculated on those days; the gaps come from the feed.
- **Yahoo CAC 40:** 6 sessions missing (24 and 31 December 2010 and 2012, 2 January 2012, 31 December 2015).
- **ECB AAA 10-year yield:** 10 sessions without a value: 24 and 31 December in 2015 and 2018 to 2020, 31 December 2024, and 14 December 2021.
- **Yahoo gold:** 3 NYSE sessions missing (2016-10-10, 2016-11-11, 2018-01-29).
- **Yahoo EUR/USD:** 1 value repeated 3 days in a row (2013-06-12), 1 daily move of +17.3% (2008-12-08, part of the August 2008 issue).
- **Volume:** not used for indices. Yahoo reports zero volume on 1,413 days for the Euro Stoxx 50 and on every day for EUR/USD.
- **FRED:** unavailable from 2026-10-21 to the morning of 2026-10-22 (a "proactive maintenance" page served with HTTP 200, the same day as the PHP2Shell disclosure); downloaded on 2026-10-22, 2008-01-02 to 2026-10-21.
- **FRED VIX:** published the next day, so it is one session late at each morning run (`late_data` warning).
- **FRED US 10-year minus 2-year:** quoted to two decimals in percentage points, so the same value often repeats over several days: 88 `stale_value` warnings since 2008, a property of the series rather than a feed outage.
