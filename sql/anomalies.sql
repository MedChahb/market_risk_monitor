-- Anomaly detector measured on injected errors, rebuilt by pipeline/anomaly_evaluation.py at every run.

DROP TABLE IF EXISTS gold.fact_anomaly_top_moves;
DROP TABLE IF EXISTS gold.fact_anomaly_evaluation;

CREATE TABLE gold.fact_anomaly_evaluation (
    layer_order          INTEGER          PRIMARY KEY,  -- sort key for the report
    layer                TEXT             NOT NULL UNIQUE,
    n_flags              INTEGER          NOT NULL,  -- series-days flagged in the data with injected errors
    precision            DOUBLE PRECISION,           -- share of flags on a wrong day or the session after it
    recall_spike         DOUBLE PRECISION NOT NULL,  -- share of the injected errors caught, by type
    recall_frozen        DOUBLE PRECISION NOT NULL,
    recall_decimal_shift DOUBLE PRECISION NOT NULL,
    recall_split         DOUBLE PRECISION NOT NULL,
    recall_missing_days  DOUBLE PRECISION NOT NULL,
    recall_roll_jump     DOUBLE PRECISION NOT NULL,
    n_per_type           INTEGER          NOT NULL,  -- errors injected of each type
    seed                 INTEGER          NOT NULL
);

-- The largest real daily moves and the layers that flag them: a correct detector flags none.
CREATE TABLE gold.fact_anomaly_top_moves (
    date          DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    instrument_id TEXT             NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    log_return    DOUBLE PRECISION NOT NULL,
    robust_z      DOUBLE PRECISION,  -- empty in the first weeks of a series, before the 63-return window fills
    flagged_by    TEXT             NOT NULL,  -- layers that flag it, or 'none'
    PRIMARY KEY (date, instrument_id)
);
CREATE INDEX ON gold.fact_anomaly_top_moves (instrument_id);
