"""Walk-forward forecasts of the next session's traded volume for the stocks of the execution universe.

The target is the log of the next Paris session's volume (shares traded on Euronext Paris), from inputs
known before that session opens. The baseline is the 20-day average daily volume (ADV), the desks'
reference; a HAR regression on log volume and gradient-boosted trees with calendar flags, the stock's EWMA
volatility and the VIX are compared with it from 2018, refitted at the start of every month on all past
rows but the last, whose target falls in the new month. Gold stores volumes as multiples of the ADV at the
previous close: raw Yahoo volumes are not redistributed. Rebuilt at every run, after the transform stage.
"""

import argparse
import logging
import sys
import time

import numpy as np
import pandas as pd
import xgboost
from dotenv import load_dotenv
from sqlalchemy import text

from pipeline import calendars, config, db, evaluation
from pipeline.risk import ewma_variance
from pipeline.vol_models import STRESS_YEARS, TEST_START, XGB_SETTINGS, test_months

log = logging.getLogger("volume_models")

ADV_WINDOW = 20  # sessions in the average daily volume
MODELS = ("adv20", "har_volume", "xgboost_volume")
BASELINE = "adv20"
HAR_COLUMNS = ["log_volume_d", "log_volume_w", "log_volume_m"]
QUARTERLY_EXPIRY_MONTHS = (3, 6, 9, 12)  # Euro Stoxx 50 futures and options expire on these third Fridays
FORECAST_COLUMNS = ["date", "instrument_id", "model_id", "forecast_vs_adv", "actual_vs_adv"]
BAR_QUERY = text("SELECT date, instrument_id, adj_close, volume FROM silver.daily_bar")
VIX_QUERY = text("SELECT date, value FROM silver.market WHERE instrument_id = 'VIX'")


def calendar_flags(days: pd.DatetimeIndex) -> pd.DataFrame:
    """Calendar features of the sessions being forecast, all known in advance."""
    third_friday = (days.dayofweek == 4) & ((days.day - 1) // 7 == 2)
    sessions = calendars.sessions("XPAR", days.min(), days.max() + pd.Timedelta(days=40))
    last_of_month = sessions.to_series().groupby(sessions.to_period("M")).max()
    following = calendars.following_sessions("XPAR", days)
    weekdays_before_next = np.busday_count(
        days.to_numpy("datetime64[D]"), following.to_numpy("datetime64[D]")
    )
    flags = {
        "weekday": days.dayofweek,
        "third_friday": third_friday,
        "quarterly_expiry": third_friday & days.month.isin(QUARTERLY_EXPIRY_MONTHS),
        "month_end": days.isin(last_of_month),
        "pre_holiday": weekdays_before_next > 1,  # the next weekday is a holiday
    }
    return pd.DataFrame(flags, index=days).astype("int64")


def build_features(bars: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """Inputs for the session after each date: HAR terms of log volume, the stock's EWMA variance and the
    VIX at that date, and the calendar flags of the session being forecast."""
    log_volume = np.log(bars["volume"])
    returns = bars["adj_close"].pct_change() * 100
    features = pd.DataFrame(
        {
            "log_volume_d": log_volume,
            "log_volume_w": log_volume.rolling(5).mean(),
            "log_volume_m": log_volume.rolling(22).mean(),
            "log_ewma_var": np.log(ewma_variance(returns.dropna())),
        },
        index=bars.index,
    )
    if not vix.empty:
        features["log_vix"] = np.log(vix.reindex(bars.index, method="ffill"))  # US close, before Paris opens
    calendar = calendar_flags(calendars.following_sessions("XPAR", bars.index))
    return features.join(calendar.set_axis(bars.index))


def har_design(features: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(features)), features[HAR_COLUMNS].to_numpy()])


def fit_predict(model_id: str, train: pd.DataFrame, target: np.ndarray, test: pd.DataFrame) -> np.ndarray:
    """Log-volume forecasts of the test rows from a model fitted on the training rows."""
    if model_id == "har_volume":
        coefficients, *_ = np.linalg.lstsq(har_design(train), target, rcond=None)
        return har_design(test) @ coefficients
    return xgboost.XGBRegressor(**XGB_SETTINGS).fit(train, target).predict(test)


def walk_forward(model_id: str, features: pd.DataFrame, target: pd.Series, months: list) -> pd.Series:
    """Monthly refits on the rows before the month, minus the last one, whose target is in the month."""
    usable = features.dropna().index
    forecasts = []
    for month_start, days in months:
        train = usable[usable < month_start][:-1]
        train = train[target.loc[train].notna().to_numpy()]
        test = days.intersection(usable)
        if test.empty:
            continue
        predicted = fit_predict(
            model_id, features.loc[train], target.loc[train].to_numpy(), features.loc[test]
        )
        forecasts.append(pd.Series(predicted, index=test))
    return pd.concat(forecasts)


def forecast_stock(instrument: str, bars: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """Every model's forecast for each session from 2018, as multiples of the ADV at the previous close."""
    next_session = calendars.following_sessions("XPAR", bars.index)
    log_volume = np.log(bars["volume"])
    target = pd.Series(log_volume.reindex(next_session).to_numpy(), index=bars.index)
    log_adv = np.log(bars["volume"].rolling(ADV_WINDOW).mean())
    features = build_features(bars, vix)
    months = test_months(bars.index)
    test_dates = bars.index[bars.index >= TEST_START]
    frames = []
    for model_id in MODELS:
        started = time.perf_counter()
        if model_id == BASELINE:
            log_forecast = log_adv.loc[test_dates]
        else:
            log_forecast = walk_forward(model_id, features, target, months)
        dates = log_forecast.index
        frames.append(
            pd.DataFrame(
                {
                    "date": next_session[bars.index.get_indexer(dates)],
                    "instrument_id": instrument,
                    "model_id": model_id,
                    "forecast_vs_adv": np.exp(log_forecast - log_adv.loc[dates]).to_numpy(),
                    "actual_vs_adv": np.exp(target.loc[dates] - log_adv.loc[dates]).to_numpy(),
                }
            )
        )
        log.info(
            "%s %s: %d forecasts, %.1fs", instrument, model_id, len(dates), time.perf_counter() - started
        )
    return pd.concat(frames, ignore_index=True)[FORECAST_COLUMNS]


def results_table(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Per stock, period and model: squared log error, absolute percentage error, and Diebold-Mariano
    against the ADV baseline, on the sessions where every model has a forecast and the volume is known."""
    rows = []
    for instrument, group in forecasts.dropna(subset=["actual_vs_adv"]).groupby("instrument_id"):
        wide = group.pivot(index="date", columns="model_id", values="forecast_vs_adv").dropna()
        actual = group.drop_duplicates("date").set_index("date")["actual_vs_adv"].reindex(wide.index)
        periods = {f"{wide.index[0].year}-{wide.index[-1].year}": None} | {
            str(year): year for year in STRESS_YEARS
        }
        for period, year in periods.items():
            in_period = wide.index.year == year if year else np.ones(len(wide), dtype=bool)
            if not in_period.any():
                continue
            truth = actual[in_period]
            losses = {
                model: evaluation.squared_error(np.log(truth), np.log(wide.loc[in_period, model]))
                for model in wide.columns
            }
            for model in wide.columns:
                statistic, p_value = (
                    evaluation.diebold_mariano(losses[model], losses[BASELINE], horizon=1)
                    if model != BASELINE
                    else (np.nan, np.nan)
                )
                absolute_error = (wide.loc[in_period, model] - truth).abs() / truth
                rows.append(
                    {
                        "instrument_id": instrument,
                        "period": period,
                        "model_id": model,
                        "n_days": len(truth),
                        "mse_log": losses[model].mean(),
                        "mape": absolute_error.mean(),
                        "dm_stat_vs_adv": statistic,
                        "dm_p_vs_adv": p_value,
                    }
                )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Walk-forward next-session volume forecasts.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        bars = pd.read_sql(BAR_QUERY, conn, parse_dates=["date"])
        vix = pd.read_sql(VIX_QUERY, conn, parse_dates=["date"]).set_index("date")["value"]
    log.info("VIX input: %s", f"{vix.index.min():%Y-%m-%d} onwards" if not vix.empty else "not available")
    forecasts = pd.concat(
        [
            forecast_stock(instrument, rows.set_index("date").sort_index(), vix)
            for instrument, rows in bars.groupby("instrument_id")
        ],
        ignore_index=True,
    )
    table = results_table(forecasts)
    with engine.begin() as conn:
        db.run_sql_file(conn, "volume.sql")
        db.insert(conn, "gold", "fact_volume_forecast", forecasts)
        db.insert(conn, "gold", "fact_volume_evaluation", table)

    whole = table[table["period"].str.contains("-")]
    summary = whole.pivot(index="instrument_id", columns="model_id", values="mse_log")
    log.info("mean squared error of log volume (lower is better):\n%s", summary.round(4).to_string())
    log.info(
        "gold.fact_volume_forecast: %d rows; gold.fact_volume_evaluation: %d rows", len(forecasts), len(table)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
