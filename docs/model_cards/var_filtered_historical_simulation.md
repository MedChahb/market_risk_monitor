# Filtered historical simulation VaR and Expected Shortfall

**Purpose.** The book's 1-day VaR 99% and ES 97.5% in euros, computed at each close for the next trading day. It is the recommended risk figure among five methods ([`notebooks/03_var.ipynb`](../../notebooks/03_var.ipynb), [`notebooks/04_backtest.ipynb`](../../notebooks/04_backtest.ipynb)).

**Data.** The book's daily P&L and the 1-day GJR-GARCH variance forecasts, since 2010.

**Method.** The last 500 book returns, each divided by its own GJR-GARCH volatility forecast, rescaled to tomorrow's forecast (Barone-Adesi, Giannopoulos and Vosper, 1999); VaR and ES are the empirical 1% quantile and the mean of the worst 2.5% of these scenarios.

**Validation.** Backtest of 3,824 days from 2012: exceptions against the 1% promised, Kupiec's proportion-of-failures test, Christoffersen's independence test, the Basel traffic light on 250 days; also by calendar stress year and by market regime.

**Results.** 38 exceptions for 38.2 expected (Kupiec p = 0.969, Christoffersen p = 0.382); 3 exceptions for 2.6 expected in 2020 and in 2022; 93% of days in the green zone and none in the red. It is the only method of the five that passes every test. By the regime known when the VaR was computed: 24 exceptions for 22.0 expected in calm markets, 10 for 9.2 in normal ones, 4 for 7.0 in stress.

**Limits.** Hypothetical P&L of constant positions (no intraday trading, fees or carry). 38 expected exceptions give the tests limited power to separate close methods. The ES is not backtested directly. The standardisation uses GJR-GARCH whatever the parametric champion.

**Monitoring.** Daily exceptions and the 250-day traffic light on the Risk page; the backtest table is rebuilt at every night run.
