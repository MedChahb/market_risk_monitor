-- Run history, model drift, rolling errors and promotion decisions, rewritten by pipeline/monitor.py and
-- pipeline/publish.py from data/monitoring/. No foreign keys: a failed run must be recorded even when it
-- left the other gold tables half built.

DROP TABLE IF EXISTS gold.fact_runs;
DROP TABLE IF EXISTS gold.fact_drift;
DROP TABLE IF EXISTS gold.fact_model_monitor;
DROP TABLE IF EXISTS gold.fact_promotion;

CREATE TABLE gold.fact_runs (
    run_id        TEXT        PRIMARY KEY,  -- Jenkins BUILD_TAG
    job           TEXT        NOT NULL CHECK (job IN ('nightly', 'retrain')),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ NOT NULL,
    status        TEXT        NOT NULL,     -- SUCCESS, FAILURE, UNSTABLE or ABORTED
    stage_reached TEXT,                     -- last stage started: the failed one when the run failed
    rows_loaded   BIGINT,                   -- rows in gold after a successful run
    dq_critical   INTEGER,                  -- failed critical quality rules of this run
    dq_warnings   INTEGER,                  -- failed warning rules of this run
    detail        TEXT                      -- promotion decision, or the failed stage
);

CREATE TABLE gold.fact_drift (
    run_id       TEXT             NOT NULL,
    measured_at  TIMESTAMPTZ      NOT NULL,
    feature      TEXT             NOT NULL,  -- return, standardised return or realised variance term of the book
    psi          DOUBLE PRECISION NOT NULL,  -- last 250 sessions against 2008-2017
    status       TEXT             NOT NULL CHECK (status IN ('stable', 'moderate', 'significant')),
    window_start DATE             NOT NULL,
    window_end   DATE             NOT NULL,
    PRIMARY KEY (run_id, feature)
);

CREATE TABLE gold.fact_model_monitor (
    date     DATE             NOT NULL,
    metric   TEXT             NOT NULL,  -- qlike_63d_book_volatility or mse_log_63d_volume
    model_id TEXT             NOT NULL,
    value    DOUBLE PRECISION NOT NULL,  -- rolling 63-session mean of the loss
    PRIMARY KEY (date, metric, model_id)
);

CREATE TABLE gold.fact_promotion (
    run_id                TEXT             PRIMARY KEY,
    decided_at            TIMESTAMPTZ      NOT NULL,
    window_start          DATE             NOT NULL,
    window_end            DATE             NOT NULL,
    champion_before       TEXT             NOT NULL,
    challenger            TEXT             NOT NULL,
    champion_qlike        DOUBLE PRECISION NOT NULL,  -- 1-day QLIKE over the window
    challenger_qlike      DOUBLE PRECISION NOT NULL,
    champion_exceptions   INTEGER          NOT NULL,  -- normal VaR 99% exceptions over the window
    challenger_exceptions INTEGER          NOT NULL,
    champion_zone         TEXT             NOT NULL,
    challenger_zone       TEXT             NOT NULL,
    promoted              BOOLEAN          NOT NULL,
    champion_after        TEXT             NOT NULL
);
