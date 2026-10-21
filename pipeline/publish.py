"""Load the data quality results into gold, then export every gold table to data/gold/<table>.parquet.

Files are exported from PostgreSQL, not from memory, so the report reads exactly what the database
holds; the run fails if a file's row count differs from its table's. Flagged values are kept only
for series whose licence allows publishing their levels.
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from dotenv import load_dotenv
from sqlalchemy import Connection, text

from pipeline import config, db, files
from pipeline.catalog import CATALOG

log = logging.getLogger("publish")

TABLES = text(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
)
QUALITY_TABLES = {
    "fact_dq": "fact_dq.parquet",
    "fact_dq_flags": "dq_flags.parquet",
    "fact_freshness": "dq_freshness.parquet",
}
TYPED_COLUMNS = text(
    "SELECT table_name, column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = :schema AND data_type IN ('date', 'integer', 'bigint')"
)


def publishable_flags(flags: pd.DataFrame) -> pd.DataFrame:
    """Hide the flagged value of series whose raw levels may not be redistributed."""
    publishable = {series.instrument for series in CATALOG if series.publish_level}
    return flags.assign(value=flags["value"].where(flags["instrument"].isin(publishable), np.nan))


def latest_run_id(fact_dq: pd.DataFrame) -> str | None:
    """The run with the most recent run_at; runs recorded before run_at existed are never the latest."""
    timed = fact_dq.dropna(subset=["run_at"])
    return None if timed.empty else timed.loc[timed["run_at"].idxmax(), "run_id"]


def load_quality_results(conn: Connection, dq_dir: Path) -> None:
    db.run_sql_file(conn, "quality.sql")
    frames = {}
    for table, file in QUALITY_TABLES.items():
        path = dq_dir / file
        if path.exists():
            frames[table] = pd.read_parquet(path)
        else:
            log.warning("%s not found: gold.%s left empty", path, table)
    latest = latest_run_id(frames["fact_dq"]) if "fact_dq" in frames else None
    for table, frame in frames.items():
        if table == "fact_dq_flags":
            frame = publishable_flags(frame)
        db.insert(conn, "gold", table, frame.assign(is_latest_run=frame["run_id"] == latest))


def read_for_parquet(conn: Connection, schema: str, table: str, typed_columns: list) -> pd.DataFrame:
    """Read a table and keep its SQL types in Parquet: dates as date32, integers as integers even with NULLs."""
    frame = pd.read_sql_table(table, conn, schema=schema)
    for _, column, data_type in [c for c in typed_columns if c[0] == table]:
        if data_type == "date":
            frame[column] = pd.to_datetime(frame[column]).dt.date  # date32 is read as a Date by Power BI
        else:
            frame[column] = frame[column].astype("Int64")
    return frame


def export_schema(conn: Connection, schema: str, out_dir: Path) -> pd.DataFrame:
    """Write every table of the schema to Parquet; return the row counts on both sides."""
    tables = sorted(conn.execute(TABLES, {"schema": schema}).scalars())
    typed_columns = conn.execute(TYPED_COLUMNS, {"schema": schema}).all()
    counts = []
    for table in tables:
        path = files.write_parquet(
            read_for_parquet(conn, schema, table, typed_columns), out_dir / f"{table}.parquet"
        )
        counts.append(
            {
                "table": table,
                "postgres_rows": db.row_count(conn, schema, table),
                "parquet_rows": pq.read_metadata(path).num_rows,
            }
        )
    for stale in out_dir.glob("*.parquet"):
        if stale.stem not in tables:
            stale.unlink()  # a table that no longer exists must not linger in the report
    return pd.DataFrame(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load quality results and export the gold tables to Parquet."
    )
    parser.add_argument("--dq-dir", type=Path, default=config.DQ_DIR)
    parser.add_argument("--gold-dir", type=Path, default=config.GOLD_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.begin() as conn:
        load_quality_results(conn, args.dq_dir)
    with engine.connect() as conn:
        counts = export_schema(conn, "gold", args.gold_dir)
    for row in counts.itertuples():
        log.info(
            "gold.%-16s postgres %7d rows | parquet %7d rows", row.table, row.postgres_rows, row.parquet_rows
        )
    mismatched = counts[counts["postgres_rows"] != counts["parquet_rows"]]
    if len(mismatched):
        log.error("row counts differ for: %s", ", ".join(mismatched["table"]))
        return 1
    log.info("%d gold tables exported to %s", len(counts), args.gold_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
