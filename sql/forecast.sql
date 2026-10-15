-- Volatility forecasts, reloaded in full from data/forecasts/ at every publish.

DROP TABLE IF EXISTS gold.fact_forecast;

CREATE TABLE gold.fact_forecast (
    date         DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,  -- forecast made at this close
    series_id    TEXT             NOT NULL,  -- a position_id of gold.dim_position, or 'book'
    model_id     TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    forecast_var DOUBLE PRECISION NOT NULL CHECK (forecast_var > 0),  -- mean daily variance of the next 5 days, percent squared
    realised_var DOUBLE PRECISION,           -- the same quantity measured afterwards; empty for the last 5 days
    inputs       TEXT             NOT NULL,  -- features the model used
    PRIMARY KEY (date, series_id, model_id)
);
CREATE INDEX ON gold.fact_forecast (model_id);
