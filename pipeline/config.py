"""Project-wide settings: paths, the reporting time zone and the log format."""

from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DQ_DIR = ROOT / "data" / "dq"
GOLD_DIR = ROOT / "data" / "gold"
SQL_DIR = ROOT / "sql"

PARIS = ZoneInfo("Europe/Paris")  # download dates and as-of dates are Paris dates
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
