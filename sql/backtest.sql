-- VaR backtest, rebuilt by pipeline/backtest.py at every run.

DROP TABLE IF EXISTS gold.fact_backtest;
DROP TABLE IF EXISTS gold.fact_backtest_summary;

CREATE TABLE gold.fact_backtest (
    for_date        DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    method_id       TEXT             NOT NULL REFERENCES gold.dim_method (method_id) ON DELETE CASCADE,
    var_99_eur      DOUBLE PRECISION NOT NULL,
    pnl_eur         DOUBLE PRECISION NOT NULL,  -- book P&L of the day the VaR covers
    is_exception    BOOLEAN          NOT NULL,  -- the loss exceeded the VaR
    exceptions_250d INTEGER,                    -- exceptions over the last 250 days; empty for the first 249
    zone            TEXT CHECK (zone IN ('green', 'yellow', 'red')),  -- Basel traffic light of that count
    PRIMARY KEY (for_date, method_id)
);
CREATE INDEX ON gold.fact_backtest (method_id);

CREATE TABLE gold.fact_backtest_summary (
    method_id              TEXT             NOT NULL REFERENCES gold.dim_method (method_id) ON DELETE CASCADE,
    period                 TEXT             NOT NULL,  -- the whole period (first and last year) or a stress year
    n_days                 INTEGER          NOT NULL,
    n_exceptions           INTEGER          NOT NULL,
    expected_exceptions    DOUBLE PRECISION NOT NULL,
    kupiec_p               DOUBLE PRECISION NOT NULL,
    christoffersen_p       DOUBLE PRECISION NOT NULL,
    conditional_coverage_p DOUBLE PRECISION NOT NULL,  -- Kupiec and Christoffersen jointly
    worst_zone             TEXT,                       -- worst 250-day zone reached in the period
    zone_at_end            TEXT,                       -- zone on the last day of the period
    PRIMARY KEY (method_id, period)
);
CREATE INDEX ON gold.fact_backtest_summary (method_id);
