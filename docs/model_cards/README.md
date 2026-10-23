# Model cards

One card per model in production, with its purpose, data, validation, results, limits and monitoring. Figures are as of 23 October 2026; the notebooks recompute them from the gold tables.

| Model | Card | Feeds |
|---|---|---|
| GJR-GARCH(1,1), 1-day and 5-day volatility | [volatility_gjr_garch.md](volatility_gjr_garch.md) | Parametric and filtered historical VaR |
| Filtered historical simulation VaR and ES | [var_filtered_historical_simulation.md](var_filtered_historical_simulation.md) | Risk page, the recommended risk figure |
| XGBoost next-session volume | [volume_xgboost.md](volume_xgboost.md) | Execution page |
| Pre-trade cost (spread and square-root impact) | [trading_cost.md](trading_cost.md) | Execution page |
| Market regimes (hidden Markov model) | [market_regimes_hmm.md](market_regimes_hmm.md) | Analysis of the models by regime; Market page |
| Market data anomaly detector | [anomaly_detector.md](anomaly_detector.md) | Quality gate (`suspect_tick`) |

Owner of every model: Mohammed Chahbaoui. Scheduled runs and their monitoring: [runbook](../runbook.md).
