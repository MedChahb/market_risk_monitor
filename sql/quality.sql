-- Data quality results, reloaded in full from data/dq/ at every publish.

DROP TABLE IF EXISTS gold.fact_dq;
DROP TABLE IF EXISTS gold.fact_dq_flags;

CREATE TABLE gold.fact_dq (
    run_id     TEXT    NOT NULL,
    date       DATE    NOT NULL,  -- as-of date of the run
    source     TEXT    NOT NULL,
    instrument TEXT    NOT NULL,  -- '*' for source-level rules
    rule       TEXT    NOT NULL,
    severity   TEXT    NOT NULL CHECK (severity IN ('critical', 'warning')),
    passed     BOOLEAN NOT NULL,
    n_failed   INTEGER NOT NULL,
    PRIMARY KEY (run_id, source, instrument, rule)
);

CREATE TABLE gold.fact_dq_flags (
    run_id     TEXT NOT NULL,
    date       DATE,              -- date of the flagged observation
    source     TEXT NOT NULL,
    instrument TEXT NOT NULL,
    field      TEXT NOT NULL,
    rule       TEXT NOT NULL,
    severity   TEXT NOT NULL CHECK (severity IN ('critical', 'warning')),
    value      DOUBLE PRECISION,
    detail     TEXT NOT NULL
);
CREATE INDEX ON gold.fact_dq_flags (run_id, rule);
