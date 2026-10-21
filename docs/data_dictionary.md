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
| `VIX` | Cboe Volatility Index | FRED | `VIXCLS` | Volatility index | Index points | XNYS | Cboe data via FRED; raw data not redistributed |
| `US10Y2Y` | US 10-year minus 2-year Treasury yield | FRED | `T10Y2Y` | Rates | Percentage points | None (US bond market) | US Treasury data via FRED; raw data not redistributed |

Conventions:

- **Dates** are trading dates in the market's local time zone, stored without a time zone. `downloaded_at` is in UTC.
- **Yahoo prices** are requested with `auto_adjust=False`. For price indices `close` equals `adj_close` on every row. `GC=F` is the front-month future: its series jumps when the contract rolls.
- **Live bars:** a Yahoo bar dated today is kept only after the local close plus a buffer (Paris 18:00, New York 16:30 for the S&P 500 and 17:30 for gold, London 23:59 for EUR/USD).
- **ECB EUR/USD** is the reference rate set around 14:15 CET on TARGET business days, which match the XPAR calendar exactly since 2008. It is the rate used to convert USD positions.
- **FRED** marks a day without a value with `"."`; such days are dropped at ingestion.
- **Calendars** come from `exchange_calendars`. `US10Y2Y` follows the US bond market calendar, which that library does not provide, so it has no completeness check.

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

### `dq_flags`: one row per flagged observation

| Column | Type | Description |
|---|---|---|
| `run_id` | string | Run identifier |
| `date` | datetime64[ns] | Date of the flagged observation (empty for schema failures) |
| `source`, `instrument`, `field` | string | Where the failure is |
| `rule`, `severity` | string | Rule that failed and its severity |
| `value` | float64 | Flagged value (empty for a missing day) |
| `detail` | string | Human-readable reason |

Both tables are stored in `data/dq/` (not committed). A re-run with the same `run_id` replaces that run's rows.

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

## Known data issues (checked on 2026-10-21)

- **Yahoo EUR/USD, August 2008:** 8 observations are stored with day and month swapped. For example, the row dated 2008-01-08 (1.5571) matches the ECB rate of 2008-08-01 (1.5574). Most of August 2008 is therefore missing. Over the full history, 16 days differ from the ECB by more than 2%: the swapped rows, and days with large moves between the two fixing times (for example 2016-06-24, the day after the Brexit vote, and 2024-11-06). The ECB series is the one used for conversion.
- **Yahoo Euro Stoxx 50:** 98 XPAR sessions missing since 2008, about five a year, mostly Swiss holidays (1 August, Ascension, Whit Monday) and US holidays. The index is calculated on those days; the gaps come from the feed.
- **Yahoo CAC 40:** 6 sessions missing (24 and 31 December 2010 and 2012, 2 January 2012, 31 December 2015).
- **ECB AAA 10-year yield:** 10 sessions without a value: 24 and 31 December in 2015 and 2018 to 2020, 31 December 2024, and 14 December 2021.
- **Yahoo gold:** 3 NYSE sessions missing (2016-10-10, 2016-11-11, 2018-01-29).
- **Yahoo EUR/USD:** 1 value repeated 3 days in a row (2013-06-12), 1 daily move of +17.3% (2008-12-08, part of the August 2008 issue).
- **Volume:** not used for indices. Yahoo reports zero volume on 1,413 days for the Euro Stoxx 50 and on every day for EUR/USD.
- **FRED:** unavailable on 2026-10-21 (maintenance page served with HTTP 200); VIX and the US curve slope are reported late until the next successful download.
