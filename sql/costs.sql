-- Pre-trade cost inputs and estimates of the execution universe, rebuilt by pipeline/costs.py at every run.
-- Every row is for one Paris session and uses data up to the previous close.

DROP TABLE IF EXISTS gold.fact_cost;
DROP TABLE IF EXISTS gold.fact_liquidity;

CREATE TABLE gold.fact_liquidity (
    date               DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    instrument_id      TEXT             NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    spread_estimate_bp DOUBLE PRECISION NOT NULL,  -- Corwin-Schultz estimate from the two previous sessions, signed
    spread_bp          DOUBLE PRECISION NOT NULL CHECK (spread_bp >= 0),  -- mean of the last 63 estimates, floored at 0
    volatility_bp      DOUBLE PRECISION NOT NULL CHECK (volatility_bp > 0),  -- EWMA daily volatility forecast
    PRIMARY KEY (date, instrument_id)
);
CREATE INDEX ON gold.fact_liquidity (instrument_id);

CREATE TABLE gold.fact_cost (
    date          DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    instrument_id TEXT             NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    participation DOUBLE PRECISION NOT NULL CHECK (participation > 0 AND participation <= 1),  -- order / volume
    spread_bp     DOUBLE PRECISION NOT NULL CHECK (spread_bp >= 0),
    impact_bp     DOUBLE PRECISION NOT NULL CHECK (impact_bp >= 0),  -- 1 x volatility x sqrt(participation)
    cost_bp       DOUBLE PRECISION NOT NULL CHECK (cost_bp >= 0),    -- half the spread plus the impact
    PRIMARY KEY (date, instrument_id, participation)
);
CREATE INDEX ON gold.fact_cost (instrument_id);
