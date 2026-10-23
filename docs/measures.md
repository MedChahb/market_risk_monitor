# Measure dictionary

The 72 DAX measures of the Power BI report, by display folder, generated from the semantic model (`powerbi/MarketRiskMonitor.SemanticModel`) by `tools/document_measures.py`. Statistics such as QLIKE, Diebold-Mariano or Kupiec are computed in Python; the measures select and aggregate them.

## Data quality

### Checks (latest run)

Rules evaluated by the latest quality run, one per instrument and rule.

Format: `#,##0`

```dax
CALCULATE ( COUNTROWS ( fact_dq ), fact_dq[Latest Run] = TRUE () )
```

### Pass Rate (latest run)

Share of the latest run's checks that found no failing row.

Format: `0.0%`

```dax
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_dq ), fact_dq[Latest Run] = TRUE (), fact_dq[Passed] = TRUE () ) + 0,
    [Checks (latest run)]
)
```

### Failed Rules (latest run)

Checks of the latest run that found at least one failing row.

Format: `#,##0`

```dax
CALCULATE ( COUNTROWS ( fact_dq ), fact_dq[Latest Run] = TRUE (), fact_dq[Passed] = FALSE () )
```

### Critical Failures (latest run)

Critical checks failed by the latest run; any value above zero means the pipeline stopped.

Format: `#,##0`

```dax
CALCULATE (
    COUNTROWS ( fact_dq ),
    fact_dq[Latest Run] = TRUE (),
    fact_dq[Passed] = FALSE (),
    fact_dq[Severity] = "critical"
) + 0
```

### Warnings (latest run)

Warning checks failed by the latest run; they are reported and do not stop the pipeline.

Format: `#,##0`

```dax
CALCULATE (
    COUNTROWS ( fact_dq ),
    fact_dq[Latest Run] = TRUE (),
    fact_dq[Passed] = FALSE (),
    fact_dq[Severity] = "warning"
) + 0
```

### Flagged Rows (latest run)

Observations flagged by the latest run, all rules together.

Format: `#,##0`

```dax
CALCULATE ( SUM ( fact_dq[Failed Rows] ), fact_dq[Latest Run] = TRUE () )
```

### Failed Rules

Checks that found at least one failing row, across the runs in the current selection.

Format: `#,##0`

```dax
CALCULATE ( COUNTROWS ( fact_dq ), fact_dq[Passed] = FALSE () )
```

### Pass Rate

Share of checks that found no failing row, across the runs in the current selection.

Format: `0.0%`

```dax
DIVIDE ( CALCULATE ( COUNTROWS ( fact_dq ), fact_dq[Passed] = TRUE () ) + 0, COUNTROWS ( fact_dq ) )
```

### Series Late (latest run)

Series whose last observation is older than the last expected session, at the latest run.

Format: `#,##0`

```dax
CALCULATE (
    COUNTROWS ( fact_freshness ),
    fact_freshness[Latest Run] = TRUE (),
    fact_freshness[Is Late] = TRUE ()
) + 0
```

### Sessions Late (latest run)

Sessions missing at the end of a series at the latest run; blank when the source delivered nothing.

Format: `#,##0`

```dax
CALCULATE ( MAX ( fact_freshness[Sessions Late] ), fact_freshness[Latest Run] = TRUE () )
```

### Last Quality Run (UTC)

Start time of the latest quality run, in UTC.

Format: `dd mmm yyyy hh:nn`

```dax
MAX ( fact_dq[Run At (UTC)] )
```

## Execution

### Volume Forecast (× ADV)

Forecast volume of the session as a multiple of the 20-day ADV at the previous close. One model and one stock at a time.

Format: `0.00`

```dax
IF (
    HASONEVALUE ( dim_model[model_id] ) && HASONEVALUE ( dim_instrument[instrument_id] ),
    AVERAGE ( fact_volume_forecast[forecast_vs_adv] )
)
```

### Volume Actual (× ADV)

Shares traded on Euronext Paris in the session, as a multiple of the 20-day ADV at the previous close. One stock at a time.

Format: `0.00`

```dax
IF (
    HASONEVALUE ( dim_instrument[instrument_id] ),
    CALCULATE (
        AVERAGE ( fact_volume_forecast[actual_vs_adv] ),
        REMOVEFILTERS ( dim_model ),
        fact_volume_forecast[model_id] = "adv20"
    )
)
```

### Next Session

The session the latest forecasts and cost estimates are for, whatever the date filter.

Format: `dd mmm yyyy`

```dax
CALCULATE ( MAX ( fact_liquidity[date] ), REMOVEFILTERS ( dim_date ) )
```

### Next Session Volume (× ADV)

The selected model's volume forecast for the next session, as a multiple of the 20-day ADV.

Format: `0.00`

```dax
VAR SessionDate = [Next Session]
RETURN
    CALCULATE ( [Volume Forecast (× ADV)], REMOVEFILTERS ( dim_date ), dim_date[Date] = SessionDate )
```

### Spread (bp)

Corwin-Schultz bid-ask spread: mean of the last 63 signed estimates, floored at zero, in basis points. One stock at a time.

Format: `0.0`

```dax
IF ( HASONEVALUE ( dim_instrument[instrument_id] ), AVERAGE ( fact_liquidity[spread_bp] ) )
```

### Volatility, Daily (bp)

EWMA forecast of the daily volatility at the previous close, in basis points. One stock at a time.

Format: `0.0`

```dax
IF ( HASONEVALUE ( dim_instrument[instrument_id] ), AVERAGE ( fact_liquidity[volatility_bp] ) )
```

### Impact Constant Y

Prefactor of the square-root law; published estimates for stocks and futures range from 0.5 to 1 (Tóth, Eisler and Bouchaud, 2016).

Format: `0.0`

```dax
1
```

### Order Size

Order size chosen with the slider, as a share of the session's volume; 5% when nothing is selected.

Format: `0%`

```dax
SELECTEDVALUE ( 'Order Size Parameter'[Order Size (% of volume)], 5 ) / 100
```

### Cost at Order Size (bp)

Pre-trade cost of an order of the chosen size: half the spread plus Y x daily volatility x square root of the order size. One stock at a time.

Format: `0.0`

```dax
VAR Spread = [Spread (bp)]
VAR Volatility = [Volatility, Daily (bp)]
RETURN
    IF ( NOT ISBLANK ( Spread ), Spread / 2 + [Impact Constant Y] * Volatility * SQRT ( [Order Size] ) )
```

### Spread, Next Session (bp)

Spread estimate for the next session.

Format: `0.00`

```dax
VAR SessionDate = [Next Session]
RETURN
    CALCULATE ( [Spread (bp)], REMOVEFILTERS ( dim_date ), dim_date[Date] = SessionDate )
```

### Volatility, Next Session (bp)

Daily volatility forecast for the next session.

Format: `0.00`

```dax
VAR SessionDate = [Next Session]
RETURN
    CALCULATE ( [Volatility, Daily (bp)], REMOVEFILTERS ( dim_date ), dim_date[Date] = SessionDate )
```

### Cost at Order Size, Next Session (bp)

Pre-trade cost of an order of the chosen size in the next session, in basis points.

Format: `0.00`

```dax
VAR SessionDate = [Next Session]
RETURN
    CALCULATE ( [Cost at Order Size (bp)], REMOVEFILTERS ( dim_date ), dim_date[Date] = SessionDate )
```

### Cost Curve, Next Session (bp)

Cost in the next session for each order size of the curve's axis, from 1% to 30% of the volume.

Format: `0.0`

```dax
VAR Spread = [Spread, Next Session (bp)]
VAR Volatility = [Volatility, Next Session (bp)]
VAR Size = SELECTEDVALUE ( 'Cost Curve Axis'[Order Size, Curve (% of volume)] ) / 100
RETURN
    IF ( NOT ISBLANK ( Spread ) && NOT ISBLANK ( Size ), Spread / 2 + [Impact Constant Y] * Volatility * SQRT ( Size ) )
```

## Market

### Index (rebased to 100)

Price-like series rebased to 100 on the first date visible in the current selection. Blank for rates and for several instruments at once.

Format: `#,##0.0`

```dax
VAR FirstVisibleDate =
    CALCULATE ( MIN ( fact_market[date] ), ALLSELECTED ( dim_date ) )
VAR BaseLevel =
    CALCULATE ( SUM ( fact_market[index_100] ), REMOVEFILTERS ( dim_date ), dim_date[Date] = FirstVisibleDate )
RETURN
    IF ( HASONEVALUE ( dim_instrument[instrument_id] ), DIVIDE ( SUM ( fact_market[index_100] ), BaseLevel ) * 100 )
```

### Volatility 22d

Annualised volatility of the last 22 observed daily returns (equities, gold, FX). One instrument at a time.

Format: `0.0%`

```dax
IF ( HASONEVALUE ( dim_instrument[instrument_id] ), AVERAGE ( fact_market[vol_22d] ) )
```

### Volatility 22d (bp)

Rates: annualised volatility of the last 22 observed daily yield changes, in basis points.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_instrument[instrument_id] ), AVERAGE ( fact_market[vol_22d_bp] ) )
```

### Return

Price change between the first and the last selected date, for price-like series. One instrument at a time.

Format: `+0.0%;-0.0%;0.0%`

```dax
VAR FirstSelectedDate =
    CALCULATE ( MIN ( fact_market[date] ), ALLSELECTED ( dim_date ) )
VAR LastSelectedDate =
    CALCULATE ( MAX ( fact_market[date] ), ALLSELECTED ( dim_date ) )
VAR FirstLevel =
    CALCULATE ( SUM ( fact_market[index_100] ), REMOVEFILTERS ( dim_date ), dim_date[Date] = FirstSelectedDate )
VAR LastLevel =
    CALCULATE ( SUM ( fact_market[index_100] ), REMOVEFILTERS ( dim_date ), dim_date[Date] = LastSelectedDate )
VAR Ratio =
    DIVIDE ( LastLevel, FirstLevel )
RETURN
    IF ( HASONEVALUE ( dim_instrument[instrument_id] ) && NOT ISBLANK ( Ratio ), Ratio - 1 )
```

### Volatility (annualised)

Standard deviation of the daily returns observed over the selected dates, times the square root of 252. Filled days are left out.

Format: `0.0%`

```dax
VAR Observed =
    CALCULATETABLE (
        fact_market,
        fact_market[is_filled] = FALSE (),
        NOT ISBLANK ( fact_market[daily_return] )
    )
RETURN
    IF (
        HASONEVALUE ( dim_instrument[instrument_id] ) && COUNTROWS ( Observed ) > 1,
        STDEVX.S ( Observed, fact_market[daily_return] ) * SQRT ( 252 )
    )
```

### Volatility 22d (latest)

22-day volatility on the last selected date.

Format: `0.0%`

```dax
VAR LastSelectedDate =
    CALCULATE ( MAX ( fact_market[date] ), ALLSELECTED ( dim_date ) )
RETURN
    IF (
        HASONEVALUE ( dim_instrument[instrument_id] ),
        CALCULATE ( AVERAGE ( fact_market[vol_22d] ), REMOVEFILTERS ( dim_date ), dim_date[Date] = LastSelectedDate )
    )
```

### Volatility 22d vs Average

Latest 22-day volatility divided by its average over the selected dates; below 1 means calmer than usual.

Format: `0.00`

```dax
DIVIDE ( [Volatility 22d (latest)], [Volatility 22d] )
```

### Worst Day

Lowest daily return over the selected dates, filled days left out.

Format: `0.0%`

```dax
IF (
    HASONEVALUE ( dim_instrument[instrument_id] ),
    CALCULATE ( MIN ( fact_market[daily_return] ), fact_market[is_filled] = FALSE () )
)
```

### Max Drawdown

Deepest fall below the previous high within the selected dates. Highs are counted from the first date of the history (January 2008).

Format: `0.0%`

```dax
IF ( HASONEVALUE ( dim_instrument[instrument_id] ), MIN ( fact_market[drawdown] ) )
```

### Rate Level (%)

Rates: published level in percent (yields) or percentage points (spreads). One instrument at a time.

Format: `0.00`

```dax
IF (
    HASONEVALUE ( dim_instrument[instrument_id] ),
    CALCULATE ( AVERAGE ( fact_market[level] ), dim_instrument[Asset Class] = "rates" )
)
```

### Correlation

Correlation of daily moves (returns, or yield changes for rates) for one period. A positive value with the AAA yield means the bond price moves the other way.

Format: `0.00`

```dax
IF ( HASONEVALUE ( fact_correlation[Period] ), AVERAGE ( fact_correlation[correlation] ) )
```

### Correlation (last 250 days)

Correlation of daily moves over the last 250 reporting days, whatever period is selected.

Format: `0.00`

```dax
CALCULATE ( AVERAGE ( fact_correlation[correlation] ), fact_correlation[Period] = "Last 250 days" )
```

### Correlation (full history)

Correlation of daily moves over the whole history, whatever period is selected.

Format: `0.00`

```dax
CALCULATE ( AVERAGE ( fact_correlation[correlation] ), fact_correlation[Period] = "Full history" )
```

### Common Days

Days when both instruments of the pair moved, in the selected period.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( fact_correlation[Period] ), SUM ( fact_correlation[n_days] ) )
```

### Last Market Date

Most recent date with market data in the current selection.

Format: `dd mmm yyyy`

```dax
MAX ( fact_market[date] )
```

## Models

### Forecast Volatility

Annualised volatility forecast for the next 5 days (square root of 252 times the daily variance). One model and one series at a time.

Format: `0.0%`

```dax
IF (
    HASONEVALUE ( dim_model[model_id] ) && HASONEVALUE ( dim_series[series_id] ),
    SQRT ( 252 * AVERAGE ( fact_forecast[forecast_var] ) ) / 100
)
```

### Realised Volatility

Annualised volatility measured over the next 5 days, the quantity the models forecast. One series at a time.

Format: `0.0%`

```dax
IF (
    HASONEVALUE ( dim_series[series_id] ),
    CALCULATE (
        SQRT ( 252 * AVERAGE ( fact_forecast[realised_var] ) ) / 100,
        REMOVEFILTERS ( dim_model ),
        fact_forecast[model_id] = "har"
    )
)
```

### QLIKE

Mean QLIKE loss computed in Python (lower is better). One series and one evaluation period at a time.

Format: `0.000`

```dax
IF (
    HASONEVALUE ( fact_forecast_evaluation[Evaluation Period] ) && HASONEVALUE ( dim_series[series_id] ),
    AVERAGE ( fact_forecast_evaluation[QLIKE] )
)
```

### DM p vs HAR

Diebold-Mariano p-value of the model against HAR, computed in Python with a Newey-West variance.

Format: `0.000`

```dax
IF (
    HASONEVALUE ( fact_forecast_evaluation[Evaluation Period] ) && HASONEVALUE ( dim_series[series_id] ),
    AVERAGE ( fact_forecast_evaluation[DM p vs HAR] )
)
```

## Production

### Last Night Run Finished (UTC)

End of the latest nightly run, whatever its status.

Format: `dd mmm hh:nn`

```dax
CALCULATE ( MAX ( fact_runs[Finished (UTC)] ), REMOVEFILTERS ( fact_runs ), fact_runs[Job] = "nightly" )
```

### Last Night Run Status

Status of the latest nightly run: SUCCESS, or FAILURE when a stage such as the quality gate stopped it.

```dax
VAR LastFinish = [Last Night Run Finished (UTC)]
RETURN
    CALCULATE (
        MAX ( fact_runs[Status] ),
        REMOVEFILTERS ( fact_runs ),
        fact_runs[Job] = "nightly",
        fact_runs[Finished (UTC)] = LastFinish
    )
```

### Run Duration (min)

Minutes between the start and the end of a run, averaged over the runs in the selection.

Format: `0.0`

```dax
AVERAGEX ( fact_runs, ( fact_runs[Finished (UTC)] - fact_runs[Started (UTC)] ) * 1440 )
```

### Last Night Run Duration (min)

Duration of the latest nightly run.

Format: `0.0`

```dax
VAR LastFinish = [Last Night Run Finished (UTC)]
RETURN
    CALCULATE (
        [Run Duration (min)],
        REMOVEFILTERS ( fact_runs ),
        fact_runs[Job] = "nightly",
        fact_runs[Finished (UTC)] = LastFinish
    )
```

### Rows in Gold (last success)

Rows in the gold tables after the latest successful nightly run.

Format: `#,##0`

```dax
VAR LastSuccess =
    CALCULATE (
        MAX ( fact_runs[Finished (UTC)] ),
        REMOVEFILTERS ( fact_runs ),
        fact_runs[Job] = "nightly",
        fact_runs[Status] = "SUCCESS"
    )
RETURN
    CALCULATE ( MAX ( fact_runs[Rows Loaded] ), REMOVEFILTERS ( fact_runs ), fact_runs[Finished (UTC)] = LastSuccess )
```

### Runs

Scheduled runs in the selection, both jobs.

Format: `#,##0`

```dax
COUNTROWS ( fact_runs ) + 0
```

### Failed Runs

Scheduled runs that ended in FAILURE.

Format: `#,##0`

```dax
CALCULATE ( COUNTROWS ( fact_runs ), fact_runs[Status] = "FAILURE" ) + 0
```

### PSI (latest run)

Population stability index of each feature at the latest measurement: last 250 sessions against 2008-2017.

Format: `0.000`

```dax
VAR LatestRun = CALCULATE ( MAX ( fact_drift[Measured At (UTC)] ), REMOVEFILTERS ( fact_drift ) )
RETURN
    CALCULATE ( MAX ( fact_drift[PSI] ), fact_drift[Measured At (UTC)] = LatestRun )
```

### Drift Status (latest run)

Reading of the latest PSI: stable below 0.10, moderate to 0.25, significant above.

```dax
VAR LatestRun = CALCULATE ( MAX ( fact_drift[Measured At (UTC)] ), REMOVEFILTERS ( fact_drift ) )
RETURN
    CALCULATE ( MAX ( fact_drift[Drift Status] ), fact_drift[Measured At (UTC)] = LatestRun )
```

### Rolling Error

Rolling 63-session mean loss of a model, computed in Python after each nightly run. One metric at a time.

Format: `0.000`

```dax
IF ( HASONEVALUE ( fact_model_monitor[Monitor Metric] ), AVERAGE ( fact_model_monitor[value] ) )
```

### VaR Champion

Volatility model behind the parametric VaR after the latest promotion decision.

```dax
VAR LastDecision = CALCULATE ( MAX ( fact_promotion[Decided] ), REMOVEFILTERS ( fact_promotion ) )
VAR ModelNumber =
    CALCULATE ( MAX ( fact_promotion[After] ), fact_promotion[Decided] = LastDecision )
RETURN
    LOOKUPVALUE ( dim_model[Model], dim_model[model_id], ModelNumber )
```

## Regimes

### Probability Calm

Probability of the calm regime at each close, from the HMM refitted every January on past data only.

Format: `0%`

```dax
CALCULATE (
    AVERAGE ( fact_regime[p_calm] ),
    fact_regime[method] = "hmm",
    fact_regime[fit] = "walk_forward"
)
```

### Probability Normal

Probability of the normal regime at each close, from the HMM refitted every January on past data only.

Format: `0%`

```dax
CALCULATE (
    AVERAGE ( fact_regime[p_normal] ),
    fact_regime[method] = "hmm",
    fact_regime[fit] = "walk_forward"
)
```

### Probability Stress

Probability of the stress regime at each close, from the HMM refitted every January on past data only.

Format: `0%`

```dax
CALCULATE (
    AVERAGE ( fact_regime[p_stress] ),
    fact_regime[method] = "hmm",
    fact_regime[fit] = "walk_forward"
)
```

### Regime (latest)

Regime at the last close with data, from the walk-forward HMM, whatever the date filter.

```dax
VAR LatestRegimeDate =
    CALCULATE ( MAX ( fact_regime[date] ), REMOVEFILTERS ( dim_date ) )
VAR RegimeNumber =
    CALCULATE (
        MAX ( fact_regime[regime_id] ),
        REMOVEFILTERS ( dim_date ),
        fact_regime[date] = LatestRegimeDate,
        fact_regime[method] = "hmm",
        fact_regime[fit] = "walk_forward"
    )
RETURN
    LOOKUPVALUE ( dim_regime[Regime], dim_regime[regime_id], RegimeNumber )
```

### QLIKE by Regime

Mean QLIKE of the 5-day volatility forecasts made in each regime (walk-forward HMM), computed in Python. One series at a time.

Format: `0.000`

```dax
IF (
    HASONEVALUE ( dim_series[series_id] ),
    CALCULATE ( AVERAGE ( fact_forecast_regime[QLIKE in Regime] ), fact_forecast_regime[fit] = "walk_forward" )
)
```

## Risk

### VaR 99%

1-day VaR 99% of the book in euros, as a positive loss, for the day it covers. One method at a time.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ), SUM ( fact_var[var_99_eur] ) )
```

### Minus VaR 99%

The VaR as a negative P&L, to draw it against the daily P&L.

Format: `#,##0`

```dax
-[VaR 99%]
```

### ES 97.5%

1-day Expected Shortfall 97.5% in euros: the average loss on the worst 2.5% of days. One method at a time.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ), SUM ( fact_var[es_975_eur] ) )
```

### VaR 99% (latest)

VaR on the last day of the selection that has one. LASTNONBLANK, because dim_date runs to 31 December and its last day has no VaR.

Format: `#,##0`

```dax
IF (
    HASONEVALUE ( dim_method[method_id] ),
    CALCULATE (
        SUM ( fact_var[var_99_eur] ),
        LASTNONBLANK ( dim_date[Date], CALCULATE ( SUM ( fact_var[var_99_eur] ) ) )
    )
)
```

### ES 97.5% (latest)

Expected Shortfall on the last day of the selection that has one.

Format: `#,##0`

```dax
IF (
    HASONEVALUE ( dim_method[method_id] ),
    CALCULATE (
        SUM ( fact_var[es_975_eur] ),
        LASTNONBLANK ( dim_date[Date], CALCULATE ( SUM ( fact_var[es_975_eur] ) ) )
    )
)
```

### VaR 99% (latest), % of Book

Latest VaR as a share of the 10 M EUR book.

Format: `0.00%`

```dax
DIVIDE ( [VaR 99% (latest)], CALCULATE ( SUM ( dim_position[Notional EUR] ), REMOVEFILTERS () ) )
```

### Latest VaR Date

Day covered by the latest VaR in the selection: the next trading day after the last P&L.

Format: `dd mmm yyyy`

```dax
MAX ( fact_var[for_date] )
```

### Book P&L (normal days)

Book P&L on days the loss stayed within the selected method's VaR.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ), CALCULATE ( SUM ( fact_backtest[pnl_eur] ), fact_backtest[is_exception] = FALSE () ) )
```

### Book P&L (exception days)

Book P&L on days the loss exceeded the selected method's VaR.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ), CALCULATE ( SUM ( fact_backtest[pnl_eur] ), fact_backtest[is_exception] = TRUE () ) )
```

### Exceptions

Days in the selection when the loss exceeded the VaR of the previous close. One method at a time.

Format: `#,##0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ) && NOT ISEMPTY ( fact_backtest ), CALCULATE ( COUNTROWS ( fact_backtest ), fact_backtest[is_exception] = TRUE () ) + 0 )
```

### Expected Exceptions

1% of the backtested days in the selection: what a correct 99% VaR would give.

Format: `#,##0.0`

```dax
IF ( HASONEVALUE ( dim_method[method_id] ), COUNTROWS ( fact_backtest ) * 0.01 )
```

### Exceptions 250d

Exceptions over the 250 trading days up to the last backtested day of the selection, whatever the date filter: the Basel traffic-light count.

Format: `#,##0`

```dax
VAR LastIdx =
    CALCULATE ( MAX ( dim_date[trading_day_index] ), fact_backtest )
RETURN
    IF (
        HASONEVALUE ( dim_method[method_id] ),
        CALCULATE (
            COUNTROWS ( fact_backtest ),
            fact_backtest[is_exception] = TRUE (),
            FILTER (
                ALL ( dim_date ),
                dim_date[trading_day_index] > LastIdx - 250
                    && dim_date[trading_day_index] <= LastIdx
            )
        ) + 0
    )
```

### Traffic Light

Basel zone of the 250-day exception count: green 0 to 4, yellow 5 to 9, red 10 or more.

```dax
VAR ExceptionCount = [Exceptions 250d]
RETURN
    IF (
        NOT ISBLANK ( ExceptionCount ),
        SWITCH ( TRUE (), ExceptionCount <= 4, "Green", ExceptionCount <= 9, "Yellow", "Red" )
    )
```
