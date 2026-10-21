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
