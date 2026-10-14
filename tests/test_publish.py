import numpy as np
import pandas as pd

from pipeline import publish


def test_flagged_values_are_published_only_where_the_licence_allows():
    flags = pd.DataFrame(
        {
            "instrument": ["EURUSD", "EUR10Y_AAA", "EURUSD_YAHOO", "CAC40", "*"],
            "value": [1.12, 3.44, 1.13, 7868.05, np.nan],
            "detail": ["a", "b", "c", "d", "e"],
        }
    )
    published = publish.publishable_flags(flags)
    assert published["value"].tolist()[:2] == [1.12, 3.44]  # ECB series: reuse allowed
    assert published["value"].iloc[2:].isna().all()  # Yahoo levels and schema failures stay private
    assert published["detail"].tolist() == flags["detail"].tolist()


def test_latest_run_is_the_most_recent_timed_run():
    fact_dq = pd.DataFrame(
        {
            "run_id": ["old-untimed", "morning", "evening"],
            "run_at": pd.to_datetime([None, "2026-10-22 08:00", "2026-10-22 21:00"], utc=True),
        }
    )
    assert publish.latest_run_id(fact_dq) == "evening"
    assert publish.latest_run_id(fact_dq.iloc[:1]) is None
