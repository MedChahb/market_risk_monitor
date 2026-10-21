"""Catalog of the market data series used by the pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    instrument: str
    name: str
    source: str  # yahoo | ecb | fred
    key: str  # Yahoo ticker, ECB "flow/key", or FRED series id
    asset_class: str
    currency: str
    unit: str


CATALOG: tuple[Series, ...] = (
    Series("CAC40", "CAC 40", "yahoo", "^FCHI", "equity index", "EUR", "index points"),
    Series("SX5E", "Euro Stoxx 50", "yahoo", "^STOXX50E", "equity index", "EUR", "index points"),
    Series("SPX", "S&P 500", "yahoo", "^GSPC", "equity index", "USD", "index points"),
    Series(
        "GOLD", "Gold front-month future (COMEX)", "yahoo", "GC=F", "commodity", "USD", "USD per troy ounce"
    ),
    Series("EURUSD_YAHOO", "EUR/USD (Yahoo, cross-check)", "yahoo", "EURUSD=X", "fx", "USD", "USD per EUR"),
    Series("EURUSD", "EUR/USD ECB reference rate", "ecb", "EXR/D.USD.EUR.SP00.A", "fx", "USD", "USD per EUR"),
    Series(
        "EUR10Y_AAA",
        "Euro area AAA 10-year spot yield",
        "ecb",
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        "rates",
        "EUR",
        "percent per annum",
    ),
    Series("VIX", "Cboe Volatility Index", "fred", "VIXCLS", "volatility index", "USD", "index points"),
    Series(
        "US10Y2Y",
        "US 10-year minus 2-year Treasury yield",
        "fred",
        "T10Y2Y",
        "rates",
        "USD",
        "percentage points",
    ),
)

SOURCES = ("yahoo", "ecb", "fred")


def by_source(source: str) -> list[Series]:
    return [s for s in CATALOG if s.source == source]
