-- Daily VaR and ES of the book, rebuilt by pipeline/var.py at every run.

DROP TABLE IF EXISTS gold.fact_var;

CREATE TABLE gold.fact_var (
    for_date   DATE             NOT NULL REFERENCES gold.dim_date (date) ON DELETE CASCADE,  -- day the figure covers
    method_id  TEXT             NOT NULL REFERENCES gold.dim_method (method_id) ON DELETE CASCADE,
    var_99_eur DOUBLE PRECISION NOT NULL CHECK (var_99_eur > 0),  -- 1-day VaR 99%, as a positive loss
    es_975_eur DOUBLE PRECISION NOT NULL CHECK (es_975_eur > 0),  -- 1-day ES 97.5%, as a positive loss
    PRIMARY KEY (for_date, method_id)
);
CREATE INDEX ON gold.fact_var (method_id);
