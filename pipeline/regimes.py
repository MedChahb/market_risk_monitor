"""Daily market regimes (calm, normal, stress) from equity volatility, returns, correlation and the VIX.

A three-state Gaussian hidden Markov model fitted on the whole history describes it; its labels use
future data, so they serve for analysis, not as model inputs. A Gaussian mixture on the same features
shows what the HMM's persistence adds. A second HMM is refitted every January on past data only and
gives the filtered regime known at each close. States are ordered by average volatility. The stage
also measures VaR exceptions and volatility forecast losses by regime. Rebuilt at every run, after
the backtest stage.
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from hmmlearn import hmm
from scipy import stats
from sklearn.mixture import GaussianMixture
from sqlalchemy import text

from pipeline import config, db, evaluation, risk
from pipeline.reference import REGIMES
from pipeline.vol_models import FORECAST_FILE

log = logging.getLogger("regimes")

FEATURES = ["log_volatility", "return_22d", "correlation_63d", "log_vix"]
EQUITIES = ["CAC40", "SX5E", "SPX"]
RETURN_WINDOW = 22  # reporting days in the trailing return
CORRELATION_WINDOW = 63  # reporting days, about a quarter: shorter windows are dominated by noise
N_REGIMES = len(REGIMES)
N_STARTS = 10  # Gaussian mixture restarts; the highest likelihood is kept
START_PERSISTENCE = 0.95  # probability of staying in a state at the start of EM, which then estimates it
WALK_FORWARD_START = 2012  # first yearly refit, on 2008-2011, as the VaR history starts in 2012
PROBABILITY_COLUMNS = [f"p_{regime['name']}" for regime in REGIMES]
MARKET_QUERY = text(
    "SELECT date, instrument_id, daily_return, vol_22d, index_100, is_filled FROM gold.fact_market "
    "WHERE instrument_id IN ('CAC40', 'SX5E', 'SPX')"
)
VIX_QUERY = text("SELECT date, value FROM silver.market WHERE instrument_id = 'VIX'")
BACKTEST_QUERY = text("SELECT for_date, method_id, is_exception FROM gold.fact_backtest")


def build_features(market: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """Equity regime features at each reporting day, from data up to that day."""
    wide = market.pivot(index="date", columns="instrument_id", values=["vol_22d", "index_100"])
    returns = market.assign(observed=market["daily_return"].where(~market["is_filled"]))
    returns = returns.pivot(index="date", columns="instrument_id", values="observed")
    correlations = [
        returns[first].rolling(CORRELATION_WINDOW, min_periods=40).corr(returns[second])
        for position, first in enumerate(EQUITIES)
        for second in EQUITIES[position + 1 :]
    ]
    index_levels = wide["index_100"][EQUITIES]
    features = pd.DataFrame(
        {
            "log_volatility": np.log(wide["vol_22d"][EQUITIES].mean(axis=1)),
            "return_22d": (index_levels / index_levels.shift(RETURN_WINDOW) - 1).mean(axis=1),
            "correlation_63d": pd.concat(correlations, axis=1).mean(axis=1),
            "log_vix": np.log(vix.reindex(wide.index).ffill()),
        }
    )
    return features.dropna()


def standardise(features: pd.DataFrame, reference: pd.DataFrame) -> np.ndarray:
    return ((features - reference.mean()) / reference.std()).to_numpy()


def fit_hmm(values: np.ndarray) -> hmm.GaussianHMM:
    """EM started from k-means means and a persistent transition matrix. Random starts reach several
    optima with different labellings, and the best of ten changed with one more day of data."""
    move = (1 - START_PERSISTENCE) / (N_REGIMES - 1)
    model = hmm.GaussianHMM(N_REGIMES, covariance_type="full", n_iter=1000, init_params="mc", random_state=0)
    model.startprob_ = np.full(N_REGIMES, 1 / N_REGIMES)
    model.transmat_ = np.full((N_REGIMES, N_REGIMES), move) + np.eye(N_REGIMES) * (START_PERSISTENCE - move)
    return model.fit(values)


def regime_order(means: np.ndarray) -> np.ndarray:
    """Column order that sorts a model's states by mean volatility (the first feature): calm first."""
    return np.argsort(means[:, 0])


def filtered_probabilities(model: hmm.GaussianHMM, values: np.ndarray) -> np.ndarray:
    """Forward algorithm: each day's state probabilities given that day and the past only."""
    log_density = np.column_stack(
        [
            stats.multivariate_normal.logpdf(values, mean, covariance)
            for mean, covariance in zip(model.means_, model.covars_, strict=True)
        ]
    )
    density = np.exp(log_density - log_density.max(axis=1, keepdims=True))
    probabilities = np.empty_like(density)
    belief = model.startprob_
    for day in range(len(values)):
        posterior = belief * density[day]
        probabilities[day] = posterior / posterior.sum()
        belief = probabilities[day] @ model.transmat_
    return probabilities


def regime_rows(dates: pd.DatetimeIndex, probabilities: np.ndarray, method: str, fit: str) -> pd.DataFrame:
    rows = pd.DataFrame(probabilities, columns=PROBABILITY_COLUMNS, index=dates)
    return rows.assign(method=method, fit=fit, regime_id=probabilities.argmax(axis=1)).rename_axis("date")


def full_history_regimes(features: pd.DataFrame) -> pd.DataFrame:
    """HMM and Gaussian mixture fitted on every day: smoothed probabilities, descriptive only."""
    values = standardise(features, features)
    model = fit_hmm(values)
    hmm_probabilities = model.predict_proba(values)[:, regime_order(model.means_)]
    mixture = GaussianMixture(N_REGIMES, covariance_type="full", n_init=N_STARTS, random_state=0).fit(values)
    mixture_probabilities = mixture.predict_proba(values)[:, regime_order(mixture.means_)]
    return pd.concat(
        [
            regime_rows(features.index, hmm_probabilities, "hmm", "full_history"),
            regime_rows(features.index, mixture_probabilities, "gmm", "full_history"),
        ]
    )


def walk_forward_regimes(features: pd.DataFrame) -> pd.DataFrame:
    """HMM refitted each January on past data, standardised with past statistics, filtered forward."""
    frames = []
    for year in range(WALK_FORWARD_START, features.index[-1].year + 1):
        train = features[features.index < pd.Timestamp(year, 1, 1)]
        model = fit_hmm(standardise(train, train))
        history = features[features.index.year <= year]
        probabilities = filtered_probabilities(model, standardise(history, train))
        rows = regime_rows(history.index, probabilities[:, regime_order(model.means_)], "hmm", "walk_forward")
        frames.append(rows[rows.index.year == year])
    return pd.concat(frames)


def mean_durations(labels: pd.Series) -> pd.Series:
    """Average length in days of an uninterrupted spell in each regime."""
    spells = labels.groupby((labels != labels.shift()).cumsum()).agg(["first", "size"])
    return spells.groupby("first")["size"].mean()


def build_profile(features: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Per method, fit and regime: frequency, persistence and average conditions in natural units."""
    natural = pd.DataFrame(
        {
            "volatility": np.exp(features["log_volatility"]),
            "return_22d": features["return_22d"],
            "correlation_63d": features["correlation_63d"],
            "vix": np.exp(features["log_vix"]),
        }
    )
    rows = []
    for (method, fit), group in regimes.groupby(["method", "fit"]):
        labels = group["regime_id"]
        means = natural.reindex(labels.index).groupby(labels.to_numpy()).mean()
        durations = mean_durations(labels)
        counts = labels.value_counts()
        for regime_id in means.index:
            rows.append(
                {
                    "method": method,
                    "fit": fit,
                    "regime_id": int(regime_id),
                    "n_days": int(counts[regime_id]),
                    "share_of_days": counts[regime_id] / len(labels),
                    "mean_duration_days": durations[regime_id],
                    **means.loc[regime_id].to_dict(),
                }
            )
    return pd.DataFrame(rows)


def build_transitions(regimes: pd.DataFrame) -> pd.DataFrame:
    """Observed day-to-day transition frequencies between regimes."""
    frames = []
    for (method, fit), group in regimes.groupby(["method", "fit"]):
        labels = group["regime_id"]
        pairs = pd.crosstab(labels.shift().dropna().astype(int).to_numpy(), labels.iloc[1:].to_numpy())
        probabilities = pairs.div(pairs.sum(axis=1), axis=0).stack().rename("probability")
        frames.append(
            probabilities.rename_axis(["regime_from", "regime_to"])
            .reset_index()
            .assign(method=method, fit=fit)
        )
    return pd.concat(frames, ignore_index=True)[["method", "fit", "regime_from", "regime_to", "probability"]]


def regime_known_before(regimes: pd.DataFrame, fit: str, dates: pd.Series) -> pd.Series:
    """Regime of the HMM fit at the reporting day before each date: what the close before it knew."""
    labels = regimes[(regimes["method"] == "hmm") & (regimes["fit"] == fit)]["regime_id"]
    return labels.shift().reindex(dates).to_numpy()


def backtest_by_regime(fact_backtest: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """VaR exceptions by the regime at the close when each VaR was computed, with Kupiec's test."""
    rows = []
    for fit in ("full_history", "walk_forward"):
        tagged = fact_backtest.assign(regime_id=regime_known_before(regimes, fit, fact_backtest["for_date"]))
        for (method_id, regime_id), group in tagged.dropna(subset=["regime_id"]).groupby(
            ["method_id", "regime_id"]
        ):
            flags = group["is_exception"].to_numpy()
            rows.append(
                {
                    "fit": fit,
                    "method_id": method_id,
                    "regime_id": int(regime_id),
                    "n_days": len(flags),
                    "n_exceptions": int(flags.sum()),
                    "expected_exceptions": len(flags) * risk.EXCEPTION_RATE,
                    "kupiec_p": risk.kupiec(flags)[1],
                }
            )
    return pd.DataFrame(rows)


def forecasts_by_regime(forecasts: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Mean QLIKE of each volatility model by the regime on the day the forecast was made."""
    known = forecasts[forecasts["realised_var"] > 0]
    rows = []
    for fit in ("full_history", "walk_forward"):
        labels = regimes[(regimes["method"] == "hmm") & (regimes["fit"] == fit)]["regime_id"]
        tagged = known.assign(
            regime_id=labels.reindex(known["date"]).to_numpy(),
            loss=evaluation.qlike(known["realised_var"], known["forecast_var"]).to_numpy(),
        ).dropna(subset=["regime_id"])
        summary = tagged.groupby(["series_id", "model_id", "regime_id"])["loss"].agg(["size", "mean"])
        rows.append(summary.reset_index().assign(fit=fit))
    table = pd.concat(rows, ignore_index=True).rename(columns={"size": "n_days", "mean": "qlike"})
    return table.astype({"regime_id": "int64"})[
        ["fit", "series_id", "model_id", "regime_id", "n_days", "qlike"]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market regimes and model errors by regime.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    engine = db.engine()
    with engine.connect() as conn:
        market = pd.read_sql(MARKET_QUERY, conn, parse_dates=["date"])
        vix = pd.read_sql(VIX_QUERY, conn, parse_dates=["date"]).set_index("date")["value"]
        fact_backtest = pd.read_sql(BACKTEST_QUERY, conn, parse_dates=["for_date"])
    features = build_features(market, vix)
    regimes = pd.concat([full_history_regimes(features), walk_forward_regimes(features)])
    forecasts = pd.read_parquet(FORECAST_FILE).assign(date=lambda d: pd.to_datetime(d["date"]))
    tables = {
        "fact_regime": regimes.reset_index()[["date", "method", "fit", "regime_id", *PROBABILITY_COLUMNS]],
        "fact_regime_profile": build_profile(features, regimes),
        "fact_regime_transition": build_transitions(regimes),
        "fact_backtest_regime": backtest_by_regime(fact_backtest, regimes),
        "fact_forecast_regime": forecasts_by_regime(forecasts, regimes),
    }
    with engine.begin() as conn:
        db.run_sql_file(conn, "regimes.sql")
        for table, frame in tables.items():
            db.insert(conn, "gold", table, frame)

    profile = tables["fact_regime_profile"]
    names = {regime["regime_id"]: regime["name"] for regime in REGIMES}
    log.info(
        "features %s to %s, %d days",
        f"{features.index.min():%Y-%m-%d}",
        f"{features.index.max():%Y-%m-%d}",
        len(features),
    )
    for row in profile[profile["method"] == "hmm"].itertuples():
        log.info(
            "%-12s %-6s %4.0f%% of days, spells of %3.0f days, volatility %4.1f%%, VIX %4.1f",
            row.fit,
            names[row.regime_id],
            row.share_of_days * 100,
            row.mean_duration_days,
            row.volatility * 100,
            row.vix,
        )
    for table, frame in tables.items():
        log.info("gold.%s: %d rows", table, len(frame))
    return 0


if __name__ == "__main__":
    sys.exit(main())
