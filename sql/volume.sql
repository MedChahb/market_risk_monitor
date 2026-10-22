-- Next-session volume forecasts of the execution universe, rebuilt by pipeline/volume_models.py at every run.
-- Volumes are multiples of the 20-day ADV at the previous close: raw Yahoo volumes are not redistributed.

DROP TABLE IF EXISTS gold.fact_volume_evaluation;
DROP TABLE IF EXISTS gold.fact_volume_forecast;

CREATE TABLE gold.fact_volume_forecast (
    date            DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,  -- session forecast
    instrument_id   TEXT             NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    model_id        TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    forecast_vs_adv DOUBLE PRECISION NOT NULL CHECK (forecast_vs_adv > 0),
    actual_vs_adv   DOUBLE PRECISION CHECK (actual_vs_adv > 0),  -- empty until the session has traded
    PRIMARY KEY (date, instrument_id, model_id)
);
CREATE INDEX ON gold.fact_volume_forecast (instrument_id);
CREATE INDEX ON gold.fact_volume_forecast (model_id);

-- Losses per stock, period and model, on the sessions where every model has a forecast.
CREATE TABLE gold.fact_volume_evaluation (
    instrument_id  TEXT             NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    period         TEXT             NOT NULL,  -- whole test period, '2020' or '2022'
    model_id       TEXT             NOT NULL REFERENCES gold.dim_model (model_id) ON DELETE CASCADE,
    n_days         INTEGER          NOT NULL,
    mse_log        DOUBLE PRECISION NOT NULL,  -- mean squared error of the log volume
    mape           DOUBLE PRECISION NOT NULL,  -- mean absolute error as a share of the actual volume
    dm_stat_vs_adv DOUBLE PRECISION,           -- Diebold-Mariano on squared log errors; negative favours the model
    dm_p_vs_adv    DOUBLE PRECISION,           -- empty for the baseline
    PRIMARY KEY (instrument_id, period, model_id)
);
CREATE INDEX ON gold.fact_volume_evaluation (model_id);
