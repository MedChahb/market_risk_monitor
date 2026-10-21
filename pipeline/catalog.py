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
    calendar: str | None = None  # exchange_calendars code, "weekdays", or None: no completeness check
    role: str = "book risk factor"  # book risk factor | model input | cross-check
    licence: str = YAHOO_LICENCE
    publish_level: bool = False  # True when the licence allows publishing the raw level


CATALOG: tuple[Series, ...] = (
    Series(
        instrument="CAC40",
        name="CAC 40",
        source="yahoo",
        key="^FCHI",
        asset_class="equity index",
        currency="EUR",
        unit="index points",
        calendar="XPAR",
    ),
    Series(
        instrument="SX5E",
        name="Euro Stoxx 50",
        source="yahoo",
        key="^STOXX50E",
        asset_class="equity index",
        currency="EUR",
        unit="index points",
        calendar="XPAR",
    ),
    Series(
        instrument="SPX",
        name="S&P 500",
        source="yahoo",
        key="^GSPC",
        asset_class="equity index",
        currency="USD",
        unit="index points",
        calendar="XNYS",
    ),
    Series(
        instrument="GOLD",
        name="Gold front-month future (COMEX)",
        source="yahoo",
        key="GC=F",
        asset_class="commodity",
        currency="USD",
        unit="USD per troy ounce",
        calendar="XNYS",
    ),
    Series(
        instrument="EURUSD_YAHOO",
        name="EUR/USD (Yahoo, cross-check)",
        source="yahoo",
        key="EURUSD=X",
        asset_class="fx",
        currency="USD",
        unit="USD per EUR",
        calendar="weekdays",
        role="cross-check",
    ),
    Series(
        instrument="EURUSD",
        name="EUR/USD ECB reference rate",
        source="ecb",
        key="EXR/D.USD.EUR.SP00.A",
        asset_class="fx",
        currency="USD",
        unit="USD per EUR",
        calendar="XPAR",
        licence=ECB_LICENCE,
        publish_level=True,
    ),
    Series(
        instrument="EUR10Y_AAA",
        name="Euro area AAA 10-year spot yield",
        source="ecb",
        key="YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        asset_class="rates",
        currency="EUR",
        unit="percent per annum",
        calendar="XPAR",
        licence=ECB_LICENCE,
        publish_level=True,
    ),
    Series(
        instrument="VIX",
        name="Cboe Volatility Index",
        source="fred",
        key="VIXCLS",
        asset_class="volatility index",
        currency="USD",
        unit="index points",
        calendar="XNYS",
        role="model input",
        licence="Cboe data via FRED; raw data not redistributed",
    ),
    Series(
        instrument="US10Y2Y",
        name="US 10-year minus 2-year Treasury yield",
        source="fred",
        key="T10Y2Y",
        asset_class="rates",
        currency="USD",
        unit="percentage points",
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
