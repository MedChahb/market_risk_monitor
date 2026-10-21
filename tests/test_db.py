"""Integration tests against PostgreSQL, in a throwaway schema. Skipped when no database is reachable."""

import uuid

import pandas as pd
import pyarrow.parquet as pq
import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from pipeline import config, db, publish


@pytest.fixture
def scratch_schema():
    load_dotenv()
    try:
        engine = db.engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except (SystemExit, OperationalError):  # no password, or no server listening
        pytest.skip("PostgreSQL not available")
    schema = f"test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    yield engine, schema
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))


def test_export_keeps_row_counts_and_types(scratch_schema, tmp_path):
    engine, schema = scratch_schema
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-10-19", "2026-10-20", "2026-10-21"]),
            "n": pd.array([1, None, 3], dtype="Int64"),
            "x": [1.5, 2.5, None],
        }
    )
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {schema}.t (date DATE NOT NULL, n INTEGER, x DOUBLE PRECISION)"))
        db.insert(conn, schema, "t", frame)
    (tmp_path / "dropped_table.parquet").write_bytes(b"")
    with engine.connect() as conn:
        counts = publish.export_schema(conn, schema, tmp_path)
    assert counts.to_dict("records") == [{"table": "t", "postgres_rows": 3, "parquet_rows": 3}]
    types = pq.read_schema(tmp_path / "t.parquet")
    assert str(types.field("date").type) == "date32[day]" and str(types.field("n").type) == "int64"
    assert not (tmp_path / "dropped_table.parquet").exists()


def test_sql_file_comments_may_contain_semicolons(scratch_schema, tmp_path, monkeypatch):
    engine, schema = scratch_schema
    (tmp_path / "t.sql").write_text(
        f"-- a comment; with a semicolon\nCREATE TABLE {schema}.u (a INTEGER); -- trailing; note\n"
    )
    monkeypatch.setattr(config, "SQL_DIR", tmp_path)
    with engine.begin() as conn:
        db.run_sql_file(conn, "t.sql")
        assert db.row_count(conn, schema, "u") == 0
