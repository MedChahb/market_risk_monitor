from datetime import date

import pandas as pd

from pipeline import raw
from pipeline.catalog import get
from tests.helpers import raw_table

DAYS = pd.bdate_range("2026-10-12", "2026-10-20")


def test_writing_the_same_day_twice_keeps_a_single_identical_file(tmp_path):
    table = raw_table("CAC40", DAYS)
    first = raw.write(table, tmp_path, "yahoo", date(2026, 10, 21))
    second = raw.write(table, tmp_path, "yahoo", date(2026, 10, 21))
    assert first == second
    assert [path.name for path in (tmp_path / "yahoo").iterdir()] == ["2026-10-21.parquet"]
    pd.testing.assert_frame_equal(pd.read_parquet(first), table)


def test_read_latest_returns_the_newest_download(tmp_path):
    raw.write(raw_table("CAC40", DAYS[:3]), tmp_path, "yahoo", date(2026, 10, 20))
    raw.write(raw_table("CAC40", DAYS), tmp_path, "yahoo", date(2026, 10, 21))
    table, path = raw.read_latest(tmp_path, "yahoo")
    assert path.name == "2026-10-21.parquet" and len(table) == len(DAYS)
    assert raw.read_latest(tmp_path, "fred") == (None, None)


def test_series_values_keeps_one_value_per_day():
    table = raw_table("CAC40", DAYS)
    duplicated = pd.concat([table, table.iloc[[2]].assign(value=999.0)], ignore_index=True)
    values = raw.series_values(duplicated, get("CAC40"))
    assert values.index.is_unique and len(values) == len(DAYS)
    assert values.loc[DAYS[2]] == 999.0  # the last row wins; the quality gate reports the duplicate
