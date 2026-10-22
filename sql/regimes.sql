-- Market regimes and model errors by regime, rebuilt by pipeline/regimes.py at every run.

DROP TABLE IF EXISTS gold.fact_forecast_regime;
DROP TABLE IF EXISTS gold.fact_backtest_regime;
DROP TABLE IF EXISTS gold.fact_regime_transition;
DROP TABLE IF EXISTS gold.fact_regime_profile;
DROP TABLE IF EXISTS gold.fact_regime;

CREATE TABLE gold.fact_regime (
    date      DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    method    TEXT             NOT NULL CHECK (method IN ('hmm', 'gmm')),
    fit       TEXT             NOT NULL CHECK (fit IN ('full_history', 'walk_forward')),  -- walk_forward: past data only
    regime_id INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,  -- most probable
    p_calm    DOUBLE PRECISION NOT NULL CHECK (p_calm BETWEEN 0 AND 1),
    p_normal  DOUBLE PRECISION NOT NULL CHECK (p_normal BETWEEN 0 AND 1),
    p_stress  DOUBLE PRECISION NOT NULL CHECK (p_stress BETWEEN 0 AND 1),
    PRIMARY KEY (date, method, fit)
);
CREATE INDEX ON gold.fact_regime (regime_id);

-- Frequency, persistence and average conditions of each regime.
CREATE TABLE gold.fact_regime_profile (
    method             TEXT             NOT NULL,
    fit                TEXT             NOT NULL,
    regime_id          INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,
    n_days             INTEGER          NOT NULL,
    share_of_days      DOUBLE PRECISION NOT NULL,
    mean_duration_days DOUBLE PRECISION NOT NULL,  -- average uninterrupted spell
    volatility         DOUBLE PRECISION NOT NULL,  -- mean 22-day annualised volatility of the three equity indices
    return_22d         DOUBLE PRECISION NOT NULL,  -- mean 22-day return of the three equity indices
    correlation_63d    DOUBLE PRECISION NOT NULL,  -- mean pairwise 63-day correlation of their daily returns
    vix                DOUBLE PRECISION NOT NULL,  -- mean VIX level
    PRIMARY KEY (method, fit, regime_id)
);
CREATE INDEX ON gold.fact_regime_profile (regime_id);

-- Observed day-to-day transition frequencies.
CREATE TABLE gold.fact_regime_transition (
    method      TEXT             NOT NULL,
    fit         TEXT             NOT NULL,
    regime_from INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,
    regime_to   INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,
    probability DOUBLE PRECISION NOT NULL CHECK (probability BETWEEN 0 AND 1),
    PRIMARY KEY (method, fit, regime_from, regime_to)
);
CREATE INDEX ON gold.fact_regime_transition (regime_to);

-- VaR exceptions by the HMM regime at the close when the VaR was computed.
CREATE TABLE gold.fact_backtest_regime (
    fit                 TEXT             NOT NULL,
    method_id           TEXT             NOT NULL REFERENCES gold.dim_method (method_id) ON DELETE CASCADE,
    regime_id           INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,
    n_days              INTEGER          NOT NULL,
    n_exceptions        INTEGER          NOT NULL,
    expected_exceptions DOUBLE PRECISION NOT NULL,  -- 1% of the days
    kupiec_p            DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (fit, method_id, regime_id)
);
CREATE INDEX ON gold.fact_backtest_regime (method_id);
CREATE INDEX ON gold.fact_backtest_regime (regime_id);

-- Mean QLIKE of the volatility forecasts by the HMM regime on the forecast date.
CREATE TABLE gold.fact_forecast_regime (
    fit       TEXT             NOT NULL,
    series_id TEXT             NOT NULL REFERENCES gold.dim_series (series_id) ON DELETE CASCADE,
    model_id  TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    regime_id INTEGER          NOT NULL REFERENCES gold.dim_regime (regime_id) ON DELETE CASCADE,
    n_days    INTEGER          NOT NULL,
    qlike     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (fit, series_id, model_id, regime_id)
);
CREATE INDEX ON gold.fact_forecast_regime (series_id);
CREATE INDEX ON gold.fact_forecast_regime (model_id);
CREATE INDEX ON gold.fact_forecast_regime (regime_id);
