"""Project-wide settings: paths, the reporting time zone and the log format.

Data lives in data/ beside the code unless MRM_DATA_DIR points elsewhere: the scheduled runs in the
Jenkins container mount the same folder, so the report reads what the night run wrote.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("MRM_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DQ_DIR = DATA_DIR / "dq"
GOLD_DIR = DATA_DIR / "gold"
FORECAST_DIR = DATA_DIR / "forecasts"
MONITORING_DIR = DATA_DIR / "monitoring"
RUNS_FILE = MONITORING_DIR / "runs.parquet"
DRIFT_FILE = MONITORING_DIR / "drift.parquet"
MODEL_MONITOR_FILE = MONITORING_DIR / "model_monitor.parquet"
PROMOTIONS_FILE = MONITORING_DIR / "promotions.parquet"
SQL_DIR = ROOT / "sql"
MLFLOW_URI = f"sqlite:///{DATA_DIR / 'mlflow.db'}"  # local tracking database and model registry

PARIS = ZoneInfo("Europe/Paris")  # download dates and as-of dates are Paris dates
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
