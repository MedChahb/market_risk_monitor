# GJR-GARCH(1,1) volatility forecast

**Purpose.** Forecast the variance of the book's daily return (and of each position) for the parametric VaR and for the standardisation of filtered historical simulation. It is the champion of seven models compared in [`notebooks/02_volatility.ipynb`](../../notebooks/02_volatility.ipynb), and the champion of the weekly promotion for the VaR.

**Data.** Daily EUR returns of the six positions and of the book, from the gold P&L table, since January 2008.

**Method.** GARCH(1,1) with a leverage term (Glosten, Jagannathan and Runkle, 1993) and Student-t innovations, zero mean, fitted with `arch`. Refitted at the start of every month on all past data (expanding window): from 2010 for the 1-day forecasts of the VaR, from 2018 for the 5-day forecasts of the comparison.

**Validation.** Walk-forward only. 5-day target (mean squared return of the next five days), 2,269 out-of-sample days from 2018, QLIKE loss, Diebold-Mariano tests against HAR with a Newey-West variance.

**Results.** On the book, QLIKE 0.399 against 0.427 for HAR (p = 0.080) and 0.402 for the GRU; significantly better than HAR on the six positions; the lowest loss in 2020 (0.559 against 0.654 for HAR). By the regime known at the forecast date (walk-forward HMM): 0.370 in calm, 0.392 in normal, 0.448 in stress markets, the lowest in normal and stress. For the 1-day VaR, the first promotion run kept it: QLIKE 1.606 over the last 250 days against 1.637 for GARCH and 1.650 for EWMA.

**Limits.** A single-asset model on the book's return: it ignores the correlation structure of the positions. Normal quantiles on its forecast understate the 99% loss (see the VaR card). Its gain over HAR on the book itself is not significant at 5%.

**Monitoring.** Rolling 63-session QLIKE against HAR on the Production page; weekly champion and challenger against EWMA and GARCH (lower QLIKE and Basel zone no worse); the champion is the `champion` alias of `var-volatility` in the MLflow registry.
