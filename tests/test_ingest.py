from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import requests

from pipeline import ingest, raw
from pipeline.catalog import get

CAC, SPX, EURUSD_YAHOO = get("CAC40"), get("SPX"), get("EURUSD_YAHOO")
EURUSD, VIX = get("EURUSD"), get("VIX")
NOW = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)  # 22:00 in Paris, 16:00 in New York
STAMP = pd.Timestamp(NOW)
KEY = "abcdefghijklmnopqrstuvwxyz123456"


def yahoo_frame(dates: list[str]) -> pd.DataFrame:
    prices = {
        column: np.linspace(100, 101, len(dates)) for column in ["Adj Close", "Close", "High", "Low", "Open"]
    }
    return pd.DataFrame({**prices, "Volume": [1000] * len(dates)}, index=pd.DatetimeIndex(dates))


def fake_session(status: int = 200, content_type: str = "application/json", text: str = "", payload=None):
    response = SimpleNamespace(status_code=status, headers={"content-type": content_type}, text=text)
    response.json = lambda: payload
    return SimpleNamespace(get=lambda *args, **kwargs: response)


def test_tidy_yahoo_returns_one_row_per_date_and_field():
    tidy = ingest.tidy_yahoo(yahoo_frame(["2026-10-19", "2026-10-20"]), CAC, NOW, STAMP)
    assert list(tidy.columns) == raw.COLUMNS
    assert len(tidy) == 2 * 6
    assert set(tidy["field"]) == {"adj_close", "close", "high", "low", "open", "volume"}
    assert tidy["date"].dtype == "datetime64[ns]" and tidy["value"].dtype == "float64"
    assert not tidy.duplicated(["date", "instrument", "field"]).any()


def test_tidy_yahoo_drops_missing_values():
    frame = yahoo_frame(["2026-10-19", "2026-10-20"])
    frame.loc["2026-10-20", "Close"] = np.nan
    assert len(ingest.tidy_yahoo(frame, CAC, NOW, STAMP)) == 2 * 6 - 1


@pytest.mark.parametrize(
    ("series", "now", "keeps_today"),
    [
        (CAC, datetime(2026, 10, 21, 14, 0, tzinfo=UTC), False),  # 16:00 Paris, market open
        (CAC, datetime(2026, 10, 21, 17, 0, tzinfo=UTC), True),  # 19:00 Paris, closed
        (SPX, datetime(2026, 10, 21, 17, 0, tzinfo=UTC), False),  # 13:00 New York, open
        (SPX, datetime(2026, 10, 21, 21, 0, tzinfo=UTC), True),  # 17:00 New York, closed
        (EURUSD_YAHOO, datetime(2026, 10, 21, 22, 59, tzinfo=UTC), False),  # 23:59 London: FX still trading
    ],
)
def test_live_bar_is_dropped_until_the_market_closes(series, now, keeps_today):
    tidy = ingest.tidy_yahoo(yahoo_frame(["2026-10-20", "2026-10-21"]), series, now, STAMP)
    assert (tidy["date"].max() == pd.Timestamp("2026-10-21")) is keeps_today


def test_parse_ecb_reads_time_period_and_obs_value():
    text = "KEY,TIME_PERIOD,OBS_VALUE\nEXR.D.USD.EUR.SP00.A,2026-10-20,1.12\nEXR.D.USD.EUR.SP00.A,2026-10-21,1.1234\n"
    tidy = ingest.parse_ecb(text, EURUSD, STAMP)
    assert tidy["value"].tolist() == [1.12, 1.1234]
    assert (tidy["field"] == "value").all() and (tidy["source"] == "ecb").all()


def test_fetch_ecb_rejects_non_csv_answer():
    with pytest.raises(ingest.SourceError, match="content-type text/html"):
        ingest.fetch_ecb(EURUSD, "2008-01-01", fake_session(content_type="text/html"))


def test_parse_fred_drops_missing_dot_values():
    payload = {
        "observations": [{"date": "2026-10-19", "value": "18.2"}, {"date": "2026-10-20", "value": "."}]
    }
    assert ingest.parse_fred(payload, VIX, STAMP)["value"].tolist() == [18.2]


def test_fred_maintenance_page_is_an_error_even_with_http_200():
    session = fake_session(content_type="text/html; charset=utf-8", text="<title>Site Maintenance</title>")
    with pytest.raises(ingest.SourceError, match="not JSON"):
        ingest.fetch_fred(VIX, "2008-01-01", session, KEY)


def test_fred_network_error_does_not_leak_the_key():
    def failing_get(*args, **kwargs):
        raise requests.ConnectionError(f"Max retries exceeded with url: /fred?api_key={KEY}")

    with pytest.raises(ingest.SourceError) as err:
        ingest.fetch_fred(VIX, "2008-01-01", SimpleNamespace(get=failing_get), KEY)
    assert KEY not in str(err.value) and "***" in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_missing_fred_key_stops_before_any_download(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(ingest, "load_dotenv", lambda: None)
    monkeypatch.setattr(ingest, "http_session", lambda: pytest.fail("no download should start"))
    with pytest.raises(SystemExit, match="FRED_API_KEY is not set"):
        ingest.main(["--sources", "fred"])
