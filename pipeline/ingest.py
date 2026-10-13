"""Download market data from Yahoo Finance, the ECB Data Portal and FRED into raw Parquet files.

Each source is written to data/raw/<source>/<download_date>.parquet as a tidy table
(date, instrument, field, value, source, downloaded_at). A source is written only if all its
series downloaded; re-running on the same day replaces the file, so the job is idempotent.
"""

import argparse
import io
import logging
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline.catalog import SOURCES, Series, by_source

log = logging.getLogger("ingest")

COLUMNS = ["date", "instrument", "field", "value", "source", "downloaded_at"]
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/{key}"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
PARIS = ZoneInfo("Europe/Paris")
TIMEOUT = (10, 60)  # seconds: connect, read

# Yahoo shows a live bar for today while the market is open; it is final only after the close.
YAHOO_FINAL_AFTER = {
    "^FCHI": ("Europe/Paris", clock(18, 0)),
    "^STOXX50E": ("Europe/Paris", clock(18, 0)),
    "^GSPC": ("America/New_York", clock(16, 30)),
    "GC=F": ("America/New_York", clock(17, 30)),
    "EURUSD=X": ("Europe/London", clock(23, 59)),
}


class SourceError(RuntimeError):
    """A source failed or returned an unexpected payload."""


def http_session() -> requests.Session:
    retry = Retry(
        total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",)
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "FRED_API_KEY is not set. Add it to .env (see .env.example) or to the Jenkins credentials."
        )
    return key


def finish(long: pd.DataFrame, series: Series, downloaded_at: pd.Timestamp) -> pd.DataFrame:
    """Common tidy format: one row per (date, instrument, field), missing values dropped."""
    out = long.assign(
        date=pd.to_datetime(long["date"]).astype("datetime64[ns]"),
        value=pd.to_numeric(long["value"], errors="coerce").astype("float64"),
        instrument=series.instrument,
        source=series.source,
        downloaded_at=downloaded_at,
    ).dropna(subset=["value"])
    if out.empty:
        raise SourceError(f"{series.source} {series.key}: no observations")
    return out[COLUMNS].sort_values(["date", "field"]).reset_index(drop=True)


# --- Yahoo Finance -----------------------------------------------------------------------------


def last_final_date(ticker: str, now: datetime) -> date:
    tz_name, final_after = YAHOO_FINAL_AFTER[ticker]
    local = now.astimezone(ZoneInfo(tz_name))
    return local.date() if local.time() >= final_after else local.date() - timedelta(days=1)


def tidy_yahoo(
    frame: pd.DataFrame, series: Series, now: datetime, downloaded_at: pd.Timestamp
) -> pd.DataFrame:
    wide = frame.rename(columns=lambda c: c.lower().replace(" ", "_"))
    index = pd.DatetimeIndex(wide.index)
    wide.index = index.tz_localize(None) if index.tz is not None else index
    wide = wide[wide.index <= pd.Timestamp(last_final_date(series.key, now))]
    long = wide.rename_axis("date").reset_index().melt(id_vars="date", var_name="field", value_name="value")
    return finish(long, series, downloaded_at)


def fetch_yahoo(series: Series, start: str, attempts: int = 4) -> pd.DataFrame:
    error = None
    for attempt in range(1, attempts + 1):
        try:
            frame = yf.download(
                series.key,
                start=start,
                interval="1d",
                auto_adjust=False,
                actions=False,
                progress=False,
                multi_level_index=False,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - yfinance raises many types; retried, then reported
            frame, error = pd.DataFrame(), exc
        if not frame.empty:
            return frame
        if attempt < attempts:
            time.sleep(2**attempt)
    raise SourceError(f"yahoo {series.key}: no data after {attempts} attempts ({error or 'empty response'})")


# --- ECB Data Portal ---------------------------------------------------------------------------


def fetch_ecb(series: Series, start: str, session: requests.Session) -> str:
    try:
        r = session.get(
            ECB_URL.format(key=series.key),
            params={"format": "csvdata", "startPeriod": start},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SourceError(f"ecb {series.key}: {type(exc).__name__}: {exc}") from None
    if r.status_code != 200 or "csv" not in r.headers.get("content-type", ""):
        raise SourceError(
            f"ecb {series.key}: HTTP {r.status_code}, content-type {r.headers.get('content-type')}"
        )
    return r.text


def parse_ecb(text: str, series: Series, downloaded_at: pd.Timestamp) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text), usecols=["TIME_PERIOD", "OBS_VALUE"])
    long = raw.rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "value"}).assign(field="value")
    return finish(long, series, downloaded_at)


# --- FRED --------------------------------------------------------------------------------------


def fetch_fred(series: Series, start: str, session: requests.Session, api_key: str) -> dict:
    params = {"series_id": series.key, "api_key": api_key, "file_type": "json", "observation_start": start}
    try:
        r = session.get(FRED_URL, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        # The request URL holds the key: mask it and drop the original traceback.
        raise SourceError(
            f"fred {series.key}: {type(exc).__name__}: {str(exc).replace(api_key, '***')}"
        ) from None
    content_type = r.headers.get("content-type", "")
    if r.status_code != 200 or "json" not in content_type:
        detail = (
            r.json().get("error_message", "") if "json" in content_type else "not JSON (maintenance page?)"
        )
        raise SourceError(f"fred {series.key}: HTTP {r.status_code}, {detail.replace(api_key, '***')}")
    return r.json()


def parse_fred(payload: dict, series: Series, downloaded_at: pd.Timestamp) -> pd.DataFrame:
    obs = pd.DataFrame(payload.get("observations", []), columns=["date", "value"])
    return finish(obs.assign(field="value"), series, downloaded_at)  # FRED writes "." for missing days


# --- Run ---------------------------------------------------------------------------------------


def download_source(
    source: str, start: str, now: datetime, session: requests.Session, api_key: str | None = None
) -> pd.DataFrame:
    downloaded_at = pd.Timestamp(now).tz_convert("UTC")
    frames = []
    for series in by_source(source):
        if source == "yahoo":
            frames.append(tidy_yahoo(fetch_yahoo(series, start), series, now, downloaded_at))
            time.sleep(1)  # spacing between tickers, Yahoo rate-limits bursts
        elif source == "ecb":
            frames.append(parse_ecb(fetch_ecb(series, start, session), series, downloaded_at))
        else:
            frames.append(parse_fred(fetch_fred(series, start, session, api_key), series, downloaded_at))
    return pd.concat(frames, ignore_index=True)


def write_raw(table: pd.DataFrame, source: str, raw_dir: Path, download_date: date) -> Path:
    path = raw_dir / source / f"{download_date:%Y-%m-%d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    table.to_parquet(tmp, index=False)
    tmp.replace(path)  # atomic: a crash never leaves a half-written file
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download raw market data.")
    parser.add_argument("--start", default="2008-01-01", help="first date to download (YYYY-MM-DD)")
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    load_dotenv()
    api_key = fred_api_key() if "fred" in args.sources else None
    now = datetime.now(UTC)
    session = http_session()
    failed = []
    for source in args.sources:
        started = time.perf_counter()
        try:
            table = download_source(source, args.start, now, session, api_key)
        except SourceError as exc:
            log.error("%s: FAILED, nothing written: %s", source, exc)
            failed.append(source)
            continue
        path = write_raw(table, source, args.raw_dir, now.astimezone(PARIS).date())
        log.info(
            "%s: %d rows, %d series, %s to %s, %.1fs -> %s",
            source,
            len(table),
            table["instrument"].nunique(),
            f"{table['date'].min():%Y-%m-%d}",
            f"{table['date'].max():%Y-%m-%d}",
            time.perf_counter() - started,
            path,
        )
    if failed:
        log.error("failed sources: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
