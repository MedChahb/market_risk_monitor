-- The trading book and its daily P&L, rebuilt from silver at every run.

DROP TABLE IF EXISTS gold.fact_pnl;
DROP TABLE IF EXISTS gold.dim_position;

CREATE TABLE gold.dim_position (
    position_id   TEXT             PRIMARY KEY,
    name          TEXT             NOT NULL,
    notional_eur  DOUBLE PRECISION NOT NULL CHECK (notional_eur > 0),
    instrument_id TEXT             REFERENCES gold.dim_instrument (instrument_id),  -- NULL for cash
    currency      TEXT             NOT NULL,
    kind          TEXT             NOT NULL CHECK (kind IN ('equity', 'commodity', 'bond', 'cash'))
);

CREATE TABLE gold.fact_pnl (
    date         DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    position_id  TEXT             NOT NULL REFERENCES gold.dim_position (position_id) ON DELETE CASCADE,
    return_local DOUBLE PRECISION NOT NULL,  -- return in the position's currency
    return_fx    DOUBLE PRECISION NOT NULL,  -- USD/EUR return for USD positions, 0 otherwise
    return_eur   DOUBLE PRECISION NOT NULL,
    pnl_eur      DOUBLE PRECISION NOT NULL,  -- notional x return in euros
    pnl_fx_eur   DOUBLE PRECISION NOT NULL,  -- part of the P&L due to the dollar
    PRIMARY KEY (date, position_id)
);
CREATE INDEX ON gold.fact_pnl (position_id);
