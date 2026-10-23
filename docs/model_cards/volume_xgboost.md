# Next-session volume forecast (XGBoost)

**Purpose.** Forecast the number of shares traded in the next Paris session for ten CAC 40 stocks, so an order can be sized and scheduled as a share of the expected volume ([`notebooks/05_execution.ipynb`](../../notebooks/05_execution.ipynb)).

**Data.** Daily volume on Euronext Paris (Yahoo, equal to Euronext's published volume) of the ten largest CAC 40 weights on 31 March 2017, since 2008; the stocks' dividend-adjusted closes; the VIX (FRED).

**Method.** Gradient-boosted trees (fixed, shallow settings never tuned on the test period) on the log of volume: the last session's log volume and its 5- and 22-session means, calendar flags of the session forecast (weekday, third Friday, quarterly expiry, month end, eve of a holiday), the stock's EWMA variance and the VIX. Refitted at the start of every month on all past sessions but the last.

**Validation.** Walk-forward from 2018; mean squared error of log volume, mean absolute percentage error of volume, Diebold-Mariano tests against the 20-day average daily volume (ADV), per stock and in 2020 and 2022.

**Results.** Mean over the ten stocks: squared log error 0.095 against 0.145 for the ADV and 0.115 for a HAR regression; absolute error 25.1% against 31.8% and 26.9%. Better than the ADV and HAR on every stock (Diebold-Mariano p below 0.0005), and better than the ADV in 2020 and 2022. Quarterly expiry Fridays trade 2.35 times the ADV and the eve of a holiday 0.54 times: the calendar is the main gain over HAR.

**Limits.** Euronext Paris volume only, not the other venues where the shares trade; no earnings dates (no free history); forecasts back-transformed with the exponential target the typical session rather than the mean. Gold stores volumes as multiples of the ADV: raw Yahoo volumes are not redistributed.

**Monitoring.** Rolling 63-session squared log error against the ADV on the Production page.
