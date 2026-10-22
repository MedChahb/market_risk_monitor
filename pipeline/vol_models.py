"""Walk-forward volatility forecasts for each position of the book and for the book itself.

Every model forecasts the average daily variance of the next 5 trading days, from EUR returns in
percent (so variances are in percent squared). Models are trained on 2008-2017, then refitted at the
start of every month from 2018 on all past data; supervised models drop the last 5 training rows,
whose targets overlap the month they forecast. Range-based variances (from open, high, low and close)
feed HAR-range and the machine-learning models for the positions that have them; the VIX and the curve
slopes enter the machine-learning models only when their series cover the whole history. Every run
records which inputs it used.
Forecasts are written to data/forecasts/ (re-running a model replaces its rows) and runs to MLflow.
"""

import argparse
import logging
import sys
import time
import warnings

import mlflow
import numpy as np
import pandas as pd
import torch
import xgboost
from arch import arch_model
from dotenv import load_dotenv
from sqlalchemy import text

from pipeline import config, db, evaluation, files
from pipeline.book import BOOK, BOOK_NOTIONAL

log = logging.getLogger("vol_models")

HORIZON = 5  # trading days in the target
TEST_START = pd.Timestamp("2018-01-01")
EWMA_DECAY = 0.94  # RiskMetrics value for daily data
EPSILON = 1e-6  # added to squared returns (percent squared) before taking logs
SEQUENCE_LENGTH = 22  # days of history the GRU reads, about a month
DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)  # GPU when the CUDA build of PyTorch finds one
MODELS = ("ewma", "garch", "gjr", "har", "har_range", "xgboost", "gru")
BASELINE = "har"
HAR_COLUMNS = ["log_rv_d", "log_rv_w", "log_rv_m"]
RANGE_COLUMNS = ["log_range_d", "log_range_w", "log_range_m"]
XGB_SETTINGS = {  # fixed and shallow, never tuned on the test period
    "n_estimators": 300,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "random_state": 0,
    "n_jobs": 4,
}
PERIODS = {"2018-2026": None, "2020": "2020", "2022": "2022"}
FORECAST_FILE = config.FORECAST_DIR / "vol_forecasts.parquet"
FORECAST_COLUMNS = ["date", "series_id", "model_id", "forecast_var", "realised_var", "inputs"]
PNL_QUERY = text("SELECT date, position_id, return_eur, pnl_eur FROM gold.fact_pnl")
SILVER_QUERY = text("SELECT date, instrument_id, value FROM silver.market")
RANGE_QUERY = text("SELECT date, instrument_id, range_variance FROM silver.daily_range")


def series_returns(pnl: pd.DataFrame) -> pd.DataFrame:
    """Daily EUR returns in percent: one column per position, plus the book."""
    pnl = pnl.assign(date=pd.to_datetime(pnl["date"]))
    returns = pnl.pivot(index="date", columns="position_id", values="return_eur") * 100
    book = pnl.groupby("date")["pnl_eur"].sum() / BOOK_NOTIONAL * 100
    return returns.assign(book=book).rename_axis(columns=None)


def exogenous_features(silver: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """VIX and curve slopes at each date; a feature is kept only if its series covers every date."""
    silver = silver.assign(date=pd.to_datetime(silver["date"]))
    levels = silver.pivot(index="date", columns="instrument_id", values="value").reindex(dates).ffill()
    candidates = {}
    if "VIX" in levels:
        candidates["log_vix"] = np.log(levels["VIX"])
    if "US10Y2Y" in levels:
        candidates["us_slope"] = levels["US10Y2Y"]
    if {"EUR10Y_AAA", "EUR2Y_AAA"} <= set(levels):
        candidates["eur_slope"] = levels["EUR10Y_AAA"] - levels["EUR2Y_AAA"]
    complete = {name: values for name, values in candidates.items() if values.notna().all()}
    return pd.DataFrame(complete, index=dates)


def realised_variance(returns: pd.Series) -> pd.Series:
    """Target at t: the mean squared return of days t+1 to t+5; missing for the last 5 days."""
    return (returns**2).rolling(HORIZON).mean().shift(-HORIZON)


def daily_weekly_monthly(variance: pd.Series, columns: list[str]) -> pd.DataFrame:
    """Logs of the variance over the last 1, 5 and 22 days: the three HAR terms."""
    windows = [variance, variance.rolling(5).mean(), variance.rolling(22).mean()]
    return pd.DataFrame(
        {column: np.log(values + EPSILON) for column, values in zip(columns, windows, strict=True)}
    )


def build_features(returns: pd.Series, exogenous: pd.DataFrame, ranges: pd.Series | None) -> pd.DataFrame:
    """Inputs known at the close of day t: HAR terms in logs, the size and sign of r_t, range-based
    HAR terms when the position has open, high, low and close, and the exogenous series."""
    features = daily_weekly_monthly(returns**2, HAR_COLUMNS).assign(
        abs_return=returns.abs(), sign=np.sign(returns)
    )
    if ranges is not None:
        features = features.join(daily_weekly_monthly(ranges, RANGE_COLUMNS))
    return features.join(exogenous)


def position_ranges(daily_range: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Range-based variance per position, on the book's dates; a day without a session counts as zero."""
    daily_range = daily_range.assign(date=pd.to_datetime(daily_range["date"]))
    wide = daily_range.pivot(index="date", columns="instrument_id", values="range_variance")
    return {
        position.position_id: wide[position.instrument].reindex(dates).fillna(0.0)
        for position in BOOK
        if position.instrument in wide
    }


def test_months(dates: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.DatetimeIndex]]:
    """(first day, days) of each month of the test period, in order."""
    test = dates[dates >= TEST_START]
    by_month = test.groupby(test.to_period("M"))
    return [(by_month[month][0], pd.DatetimeIndex(by_month[month])) for month in sorted(by_month)]


def ewma_variance(returns: pd.Series) -> pd.Series:
    """Forecast made at the close of t: decay x previous forecast + (1 - decay) x r_t squared.

    EWMA has no mean reversion, so the forecast for each of the next 5 days is the same value.
    """
    return (returns**2).ewm(alpha=1 - EWMA_DECAY, adjust=False).mean()


def garch_forecasts(returns: pd.Series, months: list, asymmetric: bool) -> pd.Series:
    """GARCH(1,1), or GJR-GARCH when asymmetric (a fall raises volatility more than a rise), with
    Student-t errors, refitted monthly; mean of the 1- to 5-day variance forecasts."""
    order = 1 if asymmetric else 0
    model = arch_model(returns, mean="Zero", vol="GARCH", p=1, o=order, q=1, dist="t", rescale=False)
    forecasts = []
    for month_start, days in months:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # convergence notes on a few refits; checked through the losses
            result = model.fit(last_obs=month_start, disp="off")
        variance = result.forecast(horizon=HORIZON, start=days[0], reindex=False).variance
        forecasts.append(variance.loc[days].mean(axis=1))
    return pd.concat(forecasts)


class Har:
    """Corsi (2009) HAR on log variances, back-transformed with Duan's smearing factor."""

    columns = HAR_COLUMNS

    def fit(self, features: pd.DataFrame, log_target: np.ndarray) -> None:
        design = self._design(features)
        self.coefficients, *_ = np.linalg.lstsq(design, log_target, rcond=None)
        self.smearing = np.mean(np.exp(log_target - design @ self.coefficients))

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.exp(self._design(features) @ self.coefficients) * self.smearing

    def _design(self, features: pd.DataFrame) -> np.ndarray:
        return np.column_stack([np.ones(len(features)), features[self.columns].to_numpy()])


class HarRange(Har):
    """HAR on range-based variances instead of squared returns."""

    columns = RANGE_COLUMNS


class Boosted:
    """Gradient-boosted trees on every feature."""

    def fit(self, features: pd.DataFrame, log_target: np.ndarray) -> None:
        self.model = xgboost.XGBRegressor(**XGB_SETTINGS)
        self.model.fit(features, log_target)
        self.smearing = np.mean(np.exp(log_target - self.model.predict(features)))

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.exp(self.model.predict(features)) * self.smearing


class GruNetwork(torch.nn.Module):
    def __init__(self, n_features: int, hidden: int) -> None:
        super().__init__()
        self.gru = torch.nn.GRU(n_features, hidden, batch_first=True)
        self.head = torch.nn.Linear(hidden, 1)

    def forward(self, sequences: torch.Tensor) -> torch.Tensor:
        output, _ = self.gru(sequences)
        return self.head(output[:, -1]).squeeze(-1)


class Gru:
    """A small GRU reading the last 22 days of features; trained from scratch at every refit."""

    hidden = 16
    epochs = 40
    batch_size = 128
    learning_rate = 1e-3

    def fit(self, sequences: np.ndarray, log_target: np.ndarray) -> None:
        torch.manual_seed(0)
        self.mean, self.std = sequences.mean(axis=(0, 1)), sequences.std(axis=(0, 1)) + 1e-8
        self.target_mean, self.target_std = log_target.mean(), log_target.std()
        inputs = self._tensor(sequences)
        target = torch.tensor(
            (log_target - self.target_mean) / self.target_std, dtype=torch.float32, device=DEVICE
        )
        self.network = GruNetwork(inputs.shape[2], self.hidden).to(DEVICE)
        optimiser = torch.optim.Adam(self.network.parameters(), lr=self.learning_rate)
        order_generator = torch.Generator().manual_seed(0)
        for _ in range(self.epochs):
            order = torch.randperm(len(inputs), generator=order_generator).to(DEVICE)
            for start in range(0, len(inputs), self.batch_size):
                batch = order[start : start + self.batch_size]
                optimiser.zero_grad()
                loss = torch.nn.functional.mse_loss(self.network(inputs[batch]), target[batch])
                loss.backward()
                optimiser.step()
        self.smearing = np.mean(np.exp(log_target - self._log_forecast(sequences)))

    def predict(self, sequences: np.ndarray) -> np.ndarray:
        return np.exp(self._log_forecast(sequences)) * self.smearing

    def _tensor(self, sequences: np.ndarray) -> torch.Tensor:
        return torch.tensor((sequences - self.mean) / self.std, dtype=torch.float32, device=DEVICE)

    def _log_forecast(self, sequences: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            standardised = self.network(self._tensor(sequences)).cpu().numpy()
        return standardised * self.target_std + self.target_mean


SUPERVISED = {"har": Har, "har_range": HarRange, "xgboost": Boosted, "gru": Gru}


def sequences(features: pd.DataFrame, dates: pd.DatetimeIndex) -> np.ndarray:
    """For each date, the feature rows of the 22 days ending on that date."""
    values = features.to_numpy(dtype=float)
    ends = features.index.get_indexer(dates)
    return np.stack([values[end - SEQUENCE_LENGTH + 1 : end + 1] for end in ends])


def walk_forward(model_id: str, features: pd.DataFrame, target: pd.Series, months: list) -> pd.Series:
    """Monthly refits on all past rows except the last 5, whose targets overlap the forecast month."""
    usable = features.dropna().index
    if model_id == "gru":
        usable = usable[SEQUENCE_LENGTH - 1 :]  # a full 22-day window of complete rows

    def inputs(dates: pd.DatetimeIndex) -> pd.DataFrame | np.ndarray:
        return sequences(features, dates) if model_id == "gru" else features.loc[dates]

    forecasts = []
    for month_start, days in months:
        train = usable[usable < month_start][:-HORIZON]
        train = train[(target.loc[train] > 0).to_numpy()]
        test = days.intersection(usable)
        model = SUPERVISED[model_id]()
        model.fit(inputs(train), np.log(target.loc[train].to_numpy()))
        forecasts.append(pd.Series(model.predict(inputs(test)), index=test))
    return pd.concat(forecasts)


def forecast_series(
    series_id: str, returns: pd.Series, exogenous: pd.DataFrame, ranges: pd.Series | None, models: list[str]
) -> pd.DataFrame:
    months = test_months(returns.index)
    test_dates = returns.index[returns.index >= TEST_START]
    features = build_features(returns, exogenous, ranges)
    target = realised_variance(returns)
    frames = []
    for model_id in models:
        if model_id == "har_range" and ranges is None:
            continue  # no open, high, low and close for this series
        started = time.perf_counter()
        if model_id == "ewma":
            forecast, inputs = ewma_variance(returns).loc[test_dates], "returns"
        elif model_id in ("garch", "gjr"):
            forecast, inputs = garch_forecasts(returns, months, asymmetric=model_id == "gjr"), "returns"
        else:
            forecast = walk_forward(model_id, features, target, months)
            inputs = ",".join(
                SUPERVISED[model_id].columns if model_id in ("har", "har_range") else features.columns
            )
        frames.append(
            pd.DataFrame(
                {
                    "date": forecast.index,
                    "series_id": series_id,
                    "model_id": model_id,
                    "forecast_var": forecast.to_numpy(),
                    "realised_var": target.reindex(forecast.index).to_numpy(),
                    "inputs": inputs,
                }
            )
        )
        log.info(
            "%s %s: %d forecasts, %.1fs", series_id, model_id, len(forecast), time.perf_counter() - started
        )
    if not frames:
        return pd.DataFrame(columns=FORECAST_COLUMNS)
    return pd.concat(frames, ignore_index=True)[FORECAST_COLUMNS]


def results_table(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Mean QLIKE and squared error per series, period and model, with Diebold-Mariano against HAR.

    Models are compared on the dates where all of them have a forecast and the realised variance is known.
    """
    rows = []
    for series_id, group in forecasts.groupby("series_id"):
        wide = group.pivot(index="date", columns="model_id", values="forecast_var").dropna()
        realised = group.drop_duplicates("date").set_index("date")["realised_var"].reindex(wide.index)
        wide, realised = wide[realised > 0], realised[realised > 0]
        for period, year in PERIODS.items():
            in_period = wide.index.year == int(year) if year else np.ones(len(wide), dtype=bool)
            if not in_period.any():
                continue
            truth = realised[in_period]
            losses = {model: evaluation.qlike(truth, wide.loc[in_period, model]) for model in wide.columns}
            for model in wide.columns:
                statistic, p_value = (
                    evaluation.diebold_mariano(losses[model], losses[BASELINE], HORIZON)
                    if model != BASELINE and BASELINE in losses
                    else (np.nan, np.nan)
                )
                rows.append(
                    {
                        "series_id": series_id,
                        "period": period,
                        "model_id": model,
                        "n_days": len(truth),
                        "qlike": losses[model].mean(),
                        "mse": evaluation.squared_error(truth, wide.loc[in_period, model]).mean(),
                        "dm_stat_vs_har": statistic,
                        "dm_p_vs_har": p_value,
                    }
                )
    return pd.DataFrame(rows)


def store(forecasts: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Replace the rows of the models just run and keep the others; return the whole table."""
    if FORECAST_FILE.exists():
        previous = pd.read_parquet(FORECAST_FILE)
        forecasts = pd.concat([previous[~previous["model_id"].isin(models)], forecasts], ignore_index=True)
    files.write_parquet(forecasts, FORECAST_FILE)
    return forecasts


def log_runs(table: pd.DataFrame, models: list[str], inputs: pd.DataFrame) -> None:
    """One MLflow run per model: settings, the inputs used for each series, and the losses."""
    mlflow.set_tracking_uri(config.MLFLOW_URI)
    mlflow.set_experiment("volatility")
    model_settings = {
        "ewma": {"ewma_decay": EWMA_DECAY},
        "xgboost": {f"xgb_{key}": value for key, value in XGB_SETTINGS.items()},
        "gru": {"gru_hidden": Gru.hidden, "gru_epochs": Gru.epochs, "gru_sequence_length": SEQUENCE_LENGTH},
    }
    for model_id in models:
        with mlflow.start_run(run_name=model_id):
            used = inputs[inputs["model_id"] == model_id]
            mlflow.log_params(
                {
                    "model": model_id,
                    "horizon_days": HORIZON,
                    "test_start": TEST_START.date().isoformat(),
                    "refit": "monthly, expanding window, last 5 training rows purged",
                    **model_settings.get(model_id, {}),
                    **{f"inputs/{row.series_id}": row.inputs for row in used.itertuples()},
                }
            )
            for row in table[table["model_id"] == model_id].itertuples():
                mlflow.log_metric(f"qlike/{row.series_id}/{row.period}", row.qlike)
                mlflow.log_metric(f"mse/{row.series_id}/{row.period}", row.mse)
                if not np.isnan(row.dm_p_vs_har):
                    mlflow.log_metric(f"dm_p_vs_har/{row.series_id}/{row.period}", row.dm_p_vs_har)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Walk-forward volatility forecasts for the book.")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()
    torch.set_num_threads(4)

    with db.engine().connect() as conn:
        returns = series_returns(pd.read_sql(PNL_QUERY, conn))
        exogenous = exogenous_features(pd.read_sql(SILVER_QUERY, conn), returns.index)
        ranges = position_ranges(pd.read_sql(RANGE_QUERY, conn), returns.index)
    missing = sorted({"log_vix", "us_slope", "eur_slope"} - set(exogenous.columns))
    log.info("exogenous inputs: %s; not available: %s", list(exogenous.columns) or "none", missing or "none")

    forecasts = pd.concat(
        [
            forecast_series(series_id, returns[series_id], exogenous, ranges.get(series_id), args.models)
            for series_id in returns.columns
        ],
        ignore_index=True,
    )
    every_model = store(forecasts, args.models)
    table = results_table(every_model)
    inputs = forecasts.drop_duplicates(["model_id", "series_id"])[["model_id", "series_id", "inputs"]]
    log_runs(table, args.models, inputs)

    summary = table[table["period"] == "2018-2026"].pivot(
        index="series_id", columns="model_id", values="qlike"
    )
    log.info("mean QLIKE 2018-2026 (lower is better):\n%s", summary.round(3).to_string())
    log.info("forecasts: %d rows -> %s", len(every_model), FORECAST_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
