"""Record each scheduled run and the health of the models.

Jenkins calls this after every run, successful or not. The run is appended to
data/monitoring/runs.parquet: job, start and end, status, the last stage reached, the rows in gold and
the failed quality rules. After a successful nightly run it also measures drift (PSI of the book's
returns and realised variances over the last 250 sessions against the 2008-2017 training years) and the
rolling forecast errors against their baselines. Levels such as the VIX or the curve slopes are left out
of the PSI: they wander far from any past range without the models being wrong. The monitoring tables are then written to gold and to
data/gold, so the report shows a failed run even when publish did not run.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

from pipeline import config, db, evaluation, files, publish, vol_models

log = logging.getLogger("monitor")

DRIFT_FEATURES = ["return", "standardised_return", "log_rv_d", "log_rv_w", "log_rv_m"]
RECENT_WINDOW = 250  # sessions compared with the training years; a quarter is too autocorrelated
ROLLING_WINDOW = 63  # sessions in the rolling forecast errors
PSI_BINS = 10  # deciles of the training distribution
PSI_FLOOR = 1e-4  # share given to an empty bin, so the logarithm stays finite
PSI_MODERATE, PSI_SIGNIFICANT = 0.10, 0.25  # usual reading of the PSI
GOLD_ROWS = text("SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables WHERE schemaname = 'gold'")


def psi(expected: pd.Series, actual: pd.Series, bins: int = PSI_BINS) -> float:
    """Population stability index of `actual` against `expected`, on the deciles of `expected`."""
    edges = np.unique(np.quantile(expected.dropna(), np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    expected_share = np.histogram(expected.dropna(), edges)[0] / expected.notna().sum()
    actual_share = np.histogram(actual.dropna(), edges)[0] / actual.notna().sum()
    expected_share, actual_share = np.maximum(expected_share, PSI_FLOOR), np.maximum(actual_share, PSI_FLOOR)
    return float(np.sum((actual_share - expected_share) * np.log(actual_share / expected_share)))


def drift_status(value: float) -> str:
    return "significant" if value > PSI_SIGNIFICANT else "moderate" if value > PSI_MODERATE else "stable"


def drift_features(returns: pd.Series) -> pd.DataFrame:
    """The book's daily return, the return over the previous day's EWMA volatility (stable if the
    volatility forecast stays calibrated), and the HAR terms of realised variance."""
    standardised = returns / np.sqrt(vol_models.ewma_variance(returns).shift())
    har_terms = vol_models.daily_weekly_monthly(returns**2, vol_models.HAR_COLUMNS)
    return har_terms.assign(**{"return": returns, "standardised_return": standardised})


def measure_drift(features: pd.DataFrame, run_id: str, measured_at: pd.Timestamp) -> pd.DataFrame:
    """PSI of each feature over the last 250 sessions against the years before the test period."""
    training = features[features.index < vol_models.TEST_START]
    recent = features.dropna(how="all").tail(RECENT_WINDOW)
    rows = [
        {
            "run_id": run_id,
            "measured_at": measured_at,
            "feature": feature,
            "psi": psi(training[feature], recent[feature]),
            "window_start": recent.index[0],
            "window_end": recent.index[-1],
        }
        for feature in DRIFT_FEATURES
        if feature in features
    ]
    drift = pd.DataFrame(rows)
    return drift.assign(status=drift["psi"].map(drift_status))


def rolling_errors(forecasts: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Rolling 63-session errors: the book's 5-day volatility QLIKE of GJR-GARCH and HAR, and the mean
    squared log error of next-session volume of XGBoost and the 20-day ADV across the ten stocks."""
    book = forecasts[(forecasts["series_id"] == "book") & forecasts["model_id"].isin(["gjr", "har"])]
    book = book[book["realised_var"] > 0]
    qlike = book.assign(loss=evaluation.qlike(book["realised_var"], book["forecast_var"]))
    qlike = qlike.pivot(index="date", columns="model_id", values="loss").dropna()
    traded = volume[volume["model_id"].isin(["xgboost_volume", "adv20"])].dropna(subset=["actual_vs_adv"])
    squared = traded.assign(loss=np.log(traded["forecast_vs_adv"] / traded["actual_vs_adv"]) ** 2)
    squared = squared.groupby(["date", "model_id"])["loss"].mean().unstack().dropna()
    frames = []
    for metric, losses in [("qlike_63d_book_volatility", qlike), ("mse_log_63d_volume", squared)]:
        rolled = losses.rolling(ROLLING_WINDOW).mean().dropna()
        long = rolled.stack().rename("value").reset_index()
        frames.append(long.assign(metric=metric))
    return pd.concat(frames, ignore_index=True)[["date", "metric", "model_id", "value"]]


def quality_counts(run_id: str) -> tuple[int | None, int | None]:
    """Failed critical and warning rules of this run, or nothing if the quality gate did not run."""
    path = config.DQ_DIR / "fact_dq.parquet"
    if not path.exists():
        return None, None
    results = pd.read_parquet(path)
    this_run = results[results["run_id"] == run_id]
    if this_run.empty:
        return None, None
    failed = this_run[~this_run["passed"]]
    return int((failed["severity"] == "critical").sum()), int((failed["severity"] == "warning").sum())


def run_detail(job: str, status: str, stage: str | None, run_id: str) -> str | None:
    if job == "retrain" and config.PROMOTIONS_FILE.exists():
        decisions = pd.read_parquet(config.PROMOTIONS_FILE)
        decisions = decisions[decisions["run_id"] == run_id]
        if len(decisions):
            row = decisions.iloc[-1]
            verdict = "promoted" if row["promoted"] else "kept"
            return (
                f"{verdict} {row['champion_after']}: champion {row['champion_before']} QLIKE "
                f"{row['champion_qlike']:.3f} ({row['champion_zone']}), challenger {row['challenger']} "
                f"{row['challenger_qlike']:.3f} ({row['challenger_zone']})"
            )
    return f"failed at {stage}" if status != "SUCCESS" and stage else None


def append(path, row: pd.DataFrame, key: str, value: str) -> pd.DataFrame:
    """Add rows to a history file; a rerun with the same key replaces its rows."""
    history = pd.read_parquet(path) if path.exists() else row.iloc[0:0]
    table = pd.concat([history[history[key] != value], row], ignore_index=True)
    files.write_parquet(table, path)
    return table


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Record a scheduled run and the health of the models.")
    parser.add_argument("--job", choices=["nightly", "retrain"], required=True)
    parser.add_argument(
        "--status", required=True, help="Jenkins result: SUCCESS, FAILURE, UNSTABLE or ABORTED"
    )
    parser.add_argument("--started-ms", type=int, help="Jenkins start time, in milliseconds since 1970")
    parser.add_argument("--stage", help="last stage the run reached")
    parser.add_argument("--run-id", default=os.environ.get("BUILD_TAG") or f"{now:%Y%m%dT%H%M%SZ}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    started = pd.Timestamp(args.started_ms, unit="ms", tz="UTC") if args.started_ms else pd.NaT
    dq_critical, dq_warnings = quality_counts(args.run_id)
    rows_loaded = None
    if args.status == "SUCCESS":
        with engine.connect() as conn:
            rows_loaded = int(conn.execute(GOLD_ROWS).scalar_one())
    run = pd.DataFrame(
        [
            {
                "run_id": args.run_id,
                "job": args.job,
                "started_at": started,
                "finished_at": pd.Timestamp(now),
                "status": args.status,
                "stage_reached": args.stage,
                "rows_loaded": rows_loaded,
                "dq_critical": dq_critical,
                "dq_warnings": dq_warnings,
                "detail": run_detail(args.job, args.status, args.stage, args.run_id),
            }
        ]
    ).astype({"rows_loaded": "Int64", "dq_critical": "Int64", "dq_warnings": "Int64"})
    append(config.RUNS_FILE, run, "run_id", args.run_id)

    if args.job == "nightly" and args.status == "SUCCESS":
        with engine.connect() as conn:
            pnl = pd.read_sql(vol_models.PNL_QUERY, conn)
            volume = pd.read_sql(text("SELECT * FROM gold.fact_volume_forecast"), conn, parse_dates=["date"])
        returns = vol_models.series_returns(pnl)["book"]
        drift = measure_drift(drift_features(returns), args.run_id, pd.Timestamp(now))
        append(config.DRIFT_FILE, drift, "run_id", args.run_id)
        forecasts = pd.read_parquet(vol_models.FORECAST_FILE).assign(date=lambda d: pd.to_datetime(d["date"]))
        files.write_parquet(rolling_errors(forecasts, volume), config.MODEL_MONITOR_FILE)
        for row in drift.itertuples():
            log.info("drift %-10s PSI %.3f (%s)", row.feature, row.psi, row.status)

    with engine.begin() as conn:
        publish.load_monitoring(conn)
    with engine.connect() as conn:
        written = publish.export_tables(conn, "gold", publish.MONITORING_TABLES, config.GOLD_DIR)
    log.info(
        "%s run %s: %s, stage %s, gold rows %s, failed rules %s critical and %s warning; exported %s",
        args.job,
        args.run_id,
        args.status,
        args.stage,
        rows_loaded,
        dq_critical,
        dq_warnings,
        ", ".join(written),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
