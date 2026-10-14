-- Data quality results, reloaded in full from data/dq/ at every publish.

DROP TABLE IF EXISTS gold.fact_dq;
DROP TABLE IF EXISTS gold.fact_dq_flags;
DROP TABLE IF EXISTS gold.fact_freshness;

CREATE TABLE gold.fact_dq (
    run_id        TEXT        NOT NULL,
    date          DATE        NOT NULL,  -- as-of date of the run
    source        TEXT        NOT NULL,
    instrument    TEXT        NOT NULL,  -- '*' for source-level rules
    rule          TEXT        NOT NULL,
    severity      TEXT        NOT NULL CHECK (severity IN ('critical', 'warning')),
    passed        BOOLEAN     NOT NULL,
    n_failed      INTEGER     NOT NULL,
    run_at        TIMESTAMPTZ,           -- empty for runs recorded before 2026-10-22
    is_latest_run BOOLEAN     NOT NULL,
    PRIMARY KEY (run_id, source, instrument, rule)
);

CREATE TABLE gold.fact_dq_flags (
    run_id        TEXT    NOT NULL,
    date          DATE,                  -- date of the flagged observation
    source        TEXT    NOT NULL,
    instrument    TEXT    NOT NULL,
    field         TEXT    NOT NULL,
    rule          TEXT    NOT NULL,
    severity      TEXT    NOT NULL CHECK (severity IN ('critical', 'warning')),
    value         DOUBLE PRECISION,      -- kept only for series whose levels may be published
    detail        TEXT    NOT NULL,
    is_latest_run BOOLEAN NOT NULL
);
CREATE INDEX ON gold.fact_dq_flags (run_id, rule);

-- Freshness of every series at each run: last observation against the last expected session.
CREATE TABLE gold.fact_freshness (
    run_id        TEXT        NOT NULL,
    run_at        TIMESTAMPTZ NOT NULL,
    date          DATE        NOT NULL,  -- as-of date of the run
    source        TEXT        NOT NULL,
    instrument    TEXT        NOT NULL,
    last_date     DATE,                  -- empty when the source delivered nothing
    expected_date DATE        NOT NULL,  -- last session before the as-of date
    sessions_late INTEGER,               -- sessions between the two; empty when there is no data
    is_late       BOOLEAN     NOT NULL,
    is_latest_run BOOLEAN     NOT NULL,
    PRIMARY KEY (run_id, instrument)
);
