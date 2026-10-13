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
    is_filled     BOOLEAN NOT NULL,
    fill_reason   TEXT,
    PRIMARY KEY (date, instrument_id)
);
CREATE INDEX ON gold.fact_market (instrument_id);
