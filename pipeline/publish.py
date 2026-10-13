"""Load the data quality results into gold, then export every gold table to data/gold/<table>.parquet.

Files are exported from PostgreSQL, not from memory, so the report reads exactly what the database
holds; the run fails if a file's row count differs from its table's.
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from dotenv import load_dotenv
from sqlalchemy import Connection, text

from pipeline import db, quality

log = logging.getLogger("publish")

GOLD_DIR = Path(__file__).resolve().parents[1] / "data" / "gold"


def load_quality_results(conn: Connection, dq_dir: Path) -> None:
    db.run_sql_file(conn, "quality.sql")
    for table, file in [("fact_dq", "fact_dq.parquet"), ("fact_dq_flags", "dq_flags.parquet")]:
        path = dq_dir / file
        if path.exists():
            db.insert(conn, "gold", table, pd.read_parquet(path))
        else:
            log.warning("%s not found: gold.%s left empty", path, table)


def export_schema(conn: Connection, schema: str, out_dir: Path) -> pd.DataFrame:
    """Write every table of the schema to Parquet; return the row counts of both sides."""
    tables = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = :s AND table_type = 'BASE TABLE'"
        ),
        {"s": schema},
    ).scalars()
    typed_columns = conn.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :s AND data_type IN ('date', 'integer', 'bigint')"
        ),
        {"s": schema},
    ).all()
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = []
    for table in sorted(tables):
        frame = pd.read_sql_table(table, conn, schema=schema)
        for _, column, data_type in [c for c in typed_columns if c[0] == table]:
            if data_type == "date":
                frame[column] = pd.to_datetime(frame[column]).dt.date  # Parquet date32: a Date in Power BI
            else:
                frame[column] = frame[column].astype("Int64")  # stays an integer even with NULLs
        path = out_dir / f"{table}.parquet"
        tmp = path.with_suffix(".parquet.tmp")
        frame.to_parquet(tmp, index=False)
        tmp.replace(path)
        counts.append(
            {
                "table": table,
                "postgres_rows": db.row_count(conn, schema, table),
                "parquet_rows": pq.read_metadata(path).num_rows,
            }
        )
    exported = {f"{c['table']}.parquet" for c in counts}
    for stale in out_dir.glob("*.parquet"):
        if stale.name not in exported:
            stale.unlink()  # a table that no longer exists must not linger in the report
    return pd.DataFrame(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load quality results and export the gold tables to Parquet."
    )
    parser.add_argument("--dq-dir", type=Path, default=quality.DQ_DIR)
    parser.add_argument("--gold-dir", type=Path, default=GOLD_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
