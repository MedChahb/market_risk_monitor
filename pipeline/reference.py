"""Reference data for the gold dimensions that do not come from market data."""

from pipeline.catalog import ECB_LICENCE, YAHOO_LICENCE

DATA_SOURCES = [
    {
        "source_id": "yahoo",
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com",
        "licence": YAHOO_LICENCE,
    },
    {
        "source_id": "ecb",
        "name": "ECB Data Portal",
        "url": "https://data.ecb.europa.eu",
        "licence": ECB_LICENCE,
    },
    {
        "source_id": "fred",
        "name": "FRED, Federal Reserve Bank of St. Louis",
        "url": "https://fred.stlouisfed.org",
        "licence": "FRED terms of use; licences vary by series",
    },
]

MODELS = [
    {
        "model_id": "ewma",
        "name": "EWMA",
        "description": "RiskMetrics exponentially weighted variance, lambda 0.94",
    },
    {"model_id": "garch", "name": "GARCH(1,1)", "description": "GARCH(1,1) with Student-t innovations"},
    {
        "model_id": "gjr",
        "name": "GJR-GARCH(1,1)",
        "description": "GARCH(1,1) with a leverage term (Glosten, Jagannathan and Runkle) and Student-t innovations",
    },
    {
        "model_id": "har",
        "name": "HAR",
        "description": "Corsi regression on the daily, weekly and monthly mean of squared returns",
    },
    {
        "model_id": "har_range",
        "name": "HAR (range)",
        "description": "HAR on range-based variances from open, high, low and close (Garman-Klass, Yang-Zhang)",
    },
    {
        "model_id": "xgboost",
        "name": "XGBoost",
        "description": "Gradient-boosted trees on HAR and range features, curve slopes and VIX when available",
    },
    {"model_id": "gru", "name": "GRU", "description": "Recurrent network on 22-day sequences"},
]

METHODS = [
    {"method_id": "hs", "name": "Historical simulation", "description": "250-day window of book P&L"},
    {
        "method_id": "param_ewma",
        "name": "Parametric (EWMA)",
        "description": "Normal quantile, EWMA volatility",
    },
    {
        "method_id": "param_garch",
        "name": "Parametric (GARCH)",
        "description": "Normal quantile, GARCH volatility",
    },
    {
        "method_id": "param_champion",
        "name": "Parametric (champion)",
        "description": "Normal quantile, champion model",
    },
    {
        "method_id": "fhs",
        "name": "Filtered historical simulation",
        "description": "500 days of standardised returns",
    },
]

REGIMES = [
    {"regime_id": 0, "name": "calm"},
    {"regime_id": 1, "name": "normal"},
    {"regime_id": 2, "name": "stress"},
]
