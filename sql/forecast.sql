-- Volatility forecasts, reloaded in full from data/forecasts/ at every publish.

DROP TABLE IF EXISTS gold.fact_forecast;
DROP TABLE IF EXISTS gold.fact_forecast_evaluation;

CREATE TABLE gold.fact_forecast (
    date         DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,  -- forecast made at this close
    series_id    TEXT             NOT NULL REFERENCES gold.dim_series (series_id) ON DELETE CASCADE,
    model_id     TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    forecast_var DOUBLE PRECISION NOT NULL CHECK (forecast_var > 0),  -- mean daily variance of the next 5 days, percent squared
    realised_var DOUBLE PRECISION,           -- the same quantity measured afterwards; empty for the last 5 days
    inputs       TEXT             NOT NULL,  -- features the model used
    PRIMARY KEY (date, series_id, model_id)
);
CREATE INDEX ON gold.fact_forecast (model_id);
CREATE INDEX ON gold.fact_forecast (series_id);

-- Accuracy of each model per series and period, computed by pipeline/vol_models.py.
CREATE TABLE gold.fact_forecast_evaluation (
    series_id      TEXT             NOT NULL REFERENCES gold.dim_series (series_id) ON DELETE CASCADE,
    period         TEXT             NOT NULL,  -- the whole test period or a stress year
    model_id       TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    n_days         INTEGER          NOT NULL,  -- days where every model of the series has a forecast
    qlike          DOUBLE PRECISION NOT NULL,  -- mean QLIKE loss, lower is better
    mse            DOUBLE PRECISION NOT NULL,  -- mean squared error on the variance
    dm_stat_vs_har DOUBLE PRECISION,           -- Diebold-Mariano statistic against HAR; negative favours the model
    dm_p_vs_har    DOUBLE PRECISION,           -- its two-sided p-value; empty for HAR itself
    PRIMARY KEY (series_id, period, model_id)
);
CREATE INDEX ON gold.fact_forecast_evaluation (model_id);
