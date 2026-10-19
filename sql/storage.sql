-- Silver and gold tables of the storage layer, rebuilt from the raw files at every run.
-- Later stages of the same run add their own gold facts after this file has been applied.

DROP SCHEMA IF EXISTS gold CASCADE;
DROP SCHEMA IF EXISTS silver CASCADE;
CREATE SCHEMA silver;
CREATE SCHEMA gold;

-- One value per instrument and reporting day; days without an observation carry the last value.
CREATE TABLE silver.market (
    date          DATE             NOT NULL,
    instrument_id TEXT             NOT NULL,
    value         DOUBLE PRECISION NOT NULL,
    is_filled     BOOLEAN          NOT NULL,
    fill_reason   TEXT CHECK (fill_reason IN ('market_closed', 'missing_in_source')),
    PRIMARY KEY (date, instrument_id),
    CHECK (is_filled = (fill_reason IS NOT NULL))
);

-- Range-based daily variance of the Yahoo series with open, high, low and close; observed days only.
CREATE TABLE silver.daily_range (
    date           DATE             NOT NULL,
    instrument_id  TEXT             NOT NULL,
    range_variance DOUBLE PRECISION NOT NULL CHECK (range_variance >= 0),  -- percent squared
    is_fallback    BOOLEAN          NOT NULL,  -- inconsistent prices: squared close-to-close return used instead
    PRIMARY KEY (date, instrument_id)
);

-- Daily bars of the execution universe, on the days the stock traded (a day without volume is left out).
CREATE TABLE silver.daily_bar (
    date          DATE             NOT NULL,
    instrument_id TEXT             NOT NULL,
    open          DOUBLE PRECISION NOT NULL CHECK (open > 0),
    high          DOUBLE PRECISION NOT NULL CHECK (high > 0),
    low           DOUBLE PRECISION NOT NULL CHECK (low > 0),
    close         DOUBLE PRECISION NOT NULL CHECK (close > 0),
    adj_close     DOUBLE PRECISION NOT NULL CHECK (adj_close > 0),  -- close adjusted for dividends and splits
    volume        BIGINT           NOT NULL CHECK (volume > 0),     -- shares traded on Euronext Paris
    PRIMARY KEY (date, instrument_id)
);

-- Every calendar day of the covered years, so the report can mark it as a date table.
CREATE TABLE gold.dim_date (
    date              DATE    PRIMARY KEY,
    year              INTEGER NOT NULL,
    quarter           INTEGER NOT NULL,
    month             INTEGER NOT NULL,
    month_name        TEXT    NOT NULL,
    day_of_week       INTEGER NOT NULL,  -- 1 = Monday
    is_trading_day    BOOLEAN NOT NULL,  -- reporting day with data: Paris or New York open
    is_xpar_session   BOOLEAN NOT NULL,
    is_xnys_session   BOOLEAN NOT NULL,
    trading_day_index INTEGER,           -- trading days up to this date; NULL outside the data range
    is_month_end      BOOLEAN NOT NULL   -- last trading day of the month
);

CREATE TABLE gold.dim_source (
    source_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    url       TEXT NOT NULL,
    licence   TEXT NOT NULL
);

CREATE TABLE gold.dim_instrument (
    instrument_id TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    short_name    TEXT    NOT NULL,  -- label for charts and matrix headers
    asset_class   TEXT    NOT NULL,
    currency      TEXT    NOT NULL,
    unit          TEXT    NOT NULL,
    role          TEXT    NOT NULL,
    source_id     TEXT    NOT NULL REFERENCES gold.dim_source (source_id),
    source_key    TEXT    NOT NULL,
    calendar      TEXT,
    licence       TEXT    NOT NULL,
    publish_level BOOLEAN NOT NULL
);
CREATE INDEX ON gold.dim_instrument (source_id);

CREATE TABLE gold.dim_model (
    model_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    target      TEXT NOT NULL CHECK (target IN ('volatility', 'volume')),  -- what the model forecasts
    description TEXT NOT NULL
);

CREATE TABLE gold.dim_method (
    method_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE gold.dim_regime (
    regime_id INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL
);

CREATE TABLE gold.fact_market (
    date          DATE    NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,
    instrument_id TEXT    NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    level         DOUBLE PRECISION,  -- raw level, only where the licence allows publishing it
    index_100     DOUBLE PRECISION,  -- price-like series rebased to 100 on their first date
    daily_return  DOUBLE PRECISION,  -- simple return: equities, gold, FX, VIX
    change_bp     DOUBLE PRECISION,  -- daily change in basis points: rates
    vol_22d       DOUBLE PRECISION,  -- annualised volatility of the last 22 observed daily returns
    vol_22d_bp    DOUBLE PRECISION,  -- rates: annualised volatility of the last 22 daily changes, in bp
    drawdown      DOUBLE PRECISION,  -- price-like series: fall below the highest level since the first date
    is_filled     BOOLEAN NOT NULL,
    fill_reason   TEXT,
    PRIMARY KEY (date, instrument_id)
);
CREATE INDEX ON gold.fact_market (instrument_id);

-- Correlation of daily moves (returns, or changes for rates) on days when both instruments moved.
CREATE TABLE gold.fact_correlation (
    period       TEXT    NOT NULL,  -- calendar year, 'Last 250 days' or 'Full history'
    period_order INTEGER NOT NULL,  -- sort key for the report
    instrument_a TEXT    NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    name_a       TEXT    NOT NULL,
    instrument_b TEXT    NOT NULL REFERENCES gold.dim_instrument (instrument_id) ON DELETE CASCADE,
    name_b       TEXT    NOT NULL,
    correlation  DOUBLE PRECISION,  -- empty when the pair has fewer than 22 common days
    n_days       INTEGER NOT NULL,  -- days when both instruments moved
    PRIMARY KEY (period, instrument_a, instrument_b)
);
CREATE INDEX ON gold.fact_correlation (instrument_a);
CREATE INDEX ON gold.fact_correlation (instrument_b);
