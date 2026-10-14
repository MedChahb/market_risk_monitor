"""PostgreSQL connection and helpers."""

import os

import pandas as pd
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL

from pipeline import config


def engine() -> Engine:
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        raise SystemExit(
            "POSTGRES_PASSWORD is not set. Add it to .env (see .env.example) or to the Jenkins credentials."
        )
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ.get("POSTGRES_USER", "mrm"),
        password=password,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),  # "db" inside the Docker network
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "mrm"),
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


def run_sql_file(conn: Connection, name: str) -> None:
    """Execute sql/<name> statement by statement; comments are stripped first, so never put -- in a string literal."""
    code = "\n".join(line.split("--")[0] for line in (config.SQL_DIR / name).read_text().splitlines())
    for statement in code.split(";"):
        if statement.strip():
            conn.execute(text(statement))


def insert(conn: Connection, schema: str, table: str, frame: pd.DataFrame) -> None:
    frame.to_sql(table, conn, schema=schema, if_exists="append", index=False, method="multi", chunksize=2000)


def row_count(conn: Connection, schema: str, table: str) -> int:
    return conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"')).scalar_one()
