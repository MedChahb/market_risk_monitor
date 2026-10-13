"""Catalog of the market data series used by the pipeline."""

from dataclasses import dataclass

YAHOO_LICENCE = "Yahoo terms: personal use; raw data not redistributed"
ECB_LICENCE = "ECB statistics: reuse with source acknowledgement"


@dataclass(frozen=True)
class Series:
    instrument: str
    name: str
    source: str  # yahoo | ecb | fred
    key: str  # Yahoo ticker, ECB "flow/key", or FRED series id
    asset_class: str
    currency: str
    unit: str
    # Trading calendar for completeness and freshness checks: an exchange_calendars code,
    # "weekdays", or None (no completeness check, freshness on weekdays).
    calendar: str | None = None
    role: str = "book risk factor"  # book risk factor | model input | cross-check
    licence: str = YAHOO_LICENCE
    publish_level: bool = False  # True when the licence allows publishing the raw level


CATALOG: tuple[Series, ...] = (
    Series("CAC40", "CAC 40", "yahoo", "^FCHI", "equity index", "EUR", "index points", "XPAR"),
    Series("SX5E", "Euro Stoxx 50", "yahoo", "^STOXX50E", "equity index", "EUR", "index points", "XPAR"),
    Series("SPX", "S&P 500", "yahoo", "^GSPC", "equity index", "USD", "index points", "XNYS"),
    Series(
        "GOLD",
        "Gold front-month future (COMEX)",
        "yahoo",
        "GC=F",
        "commodity",
        "USD",
        "USD per troy ounce",
        "XNYS",
    ),
    Series(
        "EURUSD_YAHOO",
        "EUR/USD (Yahoo, cross-check)",
        "yahoo",
        "EURUSD=X",
        "fx",
        "USD",
        "USD per EUR",
        "weekdays",
        role="cross-check",
    ),
    Series(
        "EURUSD",
        "EUR/USD ECB reference rate",
        "ecb",
        "EXR/D.USD.EUR.SP00.A",
        "fx",
        "USD",
        "USD per EUR",
        "XPAR",
        licence=ECB_LICENCE,
        publish_level=True,
    ),
    Series(
        "EUR10Y_AAA",
        "Euro area AAA 10-year spot yield",
        "ecb",
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        "rates",
        "EUR",
        "percent per annum",
        "XPAR",
        licence=ECB_LICENCE,
        publish_level=True,
    ),
    Series(
        "VIX",
        "Cboe Volatility Index",
        "fred",
        "VIXCLS",
        "volatility index",
        "USD",
        "index points",
        "XNYS",
        role="model input",
        licence="Cboe data via FRED; raw data not redistributed",
    ),
    Series(
        "US10Y2Y",
        "US 10-year minus 2-year Treasury yield",
        "fred",
        "T10Y2Y",
        "rates",
        "USD",
        "percentage points",
        role="model input",
        licence="US Treasury data via FRED; raw data not redistributed",
    ),
)

SOURCES = ("yahoo", "ecb", "fred")
FIELDS = {
    "yahoo": ("open", "high", "low", "close", "adj_close", "volume"),
    "ecb": ("value",),
    "fred": ("value",),
}


def by_source(source: str) -> list[Series]:
    return [s for s in CATALOG if s.source == source]


def get(instrument: str) -> Series:
    return next(s for s in CATALOG if s.instrument == instrument)


def main_field(series: Series) -> str:
    """The field that carries the series' level: the close for Yahoo, the single value otherwise."""
    return "close" if series.source == "yahoo" else "value"
