"""Weekly champion and challenger for the volatility model of the parametric VaR.

Over the last 250 days, each candidate's 1-day forecast (EWMA, GARCH, GJR-GARCH) is scored by QLIKE
against the next day's squared book return, and its normal VaR 99% by its exceptions and Basel zone.
The best challenger replaces the champion only if its QLIKE is lower and its zone is no worse. Every
decision is logged to MLflow and appended to data/monitoring/promotions.parquet; a promotion moves the
registry's champion alias, which the VaR stage reads.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime

import mlflow
import numpy as np
import pandas as pd
from dotenv import load_dotenv

from pipeline import backtest, config, db, evaluation, files, registry, var
from pipeline.book import BOOK_NOTIONAL

log = logging.getLogger("promotion")

WINDOW = 250  # days of the comparison, about 12 months
ZONE_RANK = {"green": 0, "yellow": 1, "red": 2}
PROMOTIONS_FILE = config.MONITORING_DIR / "promotions.parquet"


def score_candidates(pnl: pd.Series, variances: dict[str, pd.Series], window: int = WINDOW) -> pd.DataFrame:
    """QLIKE and VaR exceptions of each candidate on the last `window` days with a known next day."""
    returns = pnl / BOOK_NOTIONAL * 100
    next_squared, next_pnl = (returns**2).shift(-1), pnl.shift(-1)
    rows = []
    for model_id, variance in variances.items():
        days = variance.dropna().index.intersection(next_squared.dropna().index)[-window:]
        value_at_risk = var.NORMAL_VAR * np.sqrt(variance.loc[days]) / 100 * BOOK_NOTIONAL
        n_exceptions = int((next_pnl.loc[days] < -value_at_risk).sum())
        rows.append(
            {
                "model_id": model_id,
                "qlike": evaluation.qlike(next_squared.loc[days], variance.loc[days]).mean(),
                "n_exceptions": n_exceptions,
                "zone": backtest.zone(n_exceptions),
                "first_day": days[0],
                "last_day": days[-1],
            }
        )
    return pd.DataFrame(rows).set_index("model_id")


def decide(scores: pd.DataFrame, champion: str) -> dict:
    """Promote the challenger with the lowest QLIKE only if it also keeps the zone no worse."""
    challenger = scores.drop(index=champion)["qlike"].idxmin()
    lower_loss = scores.at[challenger, "qlike"] < scores.at[champion, "qlike"]
    zone_kept = ZONE_RANK[scores.at[challenger, "zone"]] <= ZONE_RANK[scores.at[champion, "zone"]]
    promoted = bool(lower_loss and zone_kept)
    return {
        "champion_before": champion,
        "challenger": challenger,
        "champion_qlike": scores.at[champion, "qlike"],
        "challenger_qlike": scores.at[challenger, "qlike"],
        "champion_exceptions": int(scores.at[champion, "n_exceptions"]),
        "challenger_exceptions": int(scores.at[challenger, "n_exceptions"]),
        "champion_zone": scores.at[champion, "zone"],
        "challenger_zone": scores.at[challenger, "zone"],
        "promoted": promoted,
        "champion_after": challenger if promoted else champion,
    }


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="Champion and challenger for the VaR volatility model.")
    parser.add_argument("--run-id", default=os.environ.get("BUILD_TAG") or f"{now:%Y%m%dT%H%M%SZ}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    with db.engine().connect() as conn:
        pnl = var.book_pnl(pd.read_sql(var.PNL_QUERY, conn))
    variances = var.one_day_variances(pnl / BOOK_NOTIONAL * 100)
    scores = score_candidates(pnl, {model_id: variances[model_id] for model_id in registry.CANDIDATES})
    models = registry.client()
    registered = registry.registered_champion(models)
    decision = decide(scores, registered or registry.DEFAULT_CHAMPION)

    mlflow.set_experiment("var-volatility-promotion")
    with mlflow.start_run(run_name=args.run_id) as run:
        mlflow.log_params({key: value for key, value in decision.items() if isinstance(value, str | bool)})
        for model_id, row in scores.iterrows():
            mlflow.log_metric(f"qlike/{model_id}", row["qlike"])
            mlflow.log_metric(f"exceptions/{model_id}", row["n_exceptions"])
        mlflow.log_dict(
            {**decision, "window": [str(scores["first_day"].min()), str(scores["last_day"].max())]},
            "decision.json",
        )
        if decision["promoted"] or registered is None:  # the first run registers the starting champion
            version = registry.promote(
                models, decision["champion_after"], run.info.run_id, f"{run.info.artifact_uri}/decision.json"
            )
            log.info(
                "registry: %s is version %s of %s",
                decision["champion_after"],
                version,
                registry.REGISTERED_MODEL,
            )

    row = pd.DataFrame(
        [
            {
                "run_id": args.run_id,
                "decided_at": pd.Timestamp(now),
                "window_start": scores["first_day"].min(),
                "window_end": scores["last_day"].max(),
                **decision,
            }
        ]
    )
    history = pd.read_parquet(PROMOTIONS_FILE) if PROMOTIONS_FILE.exists() else row.iloc[0:0]
    files.write_parquet(
        pd.concat([history[history["run_id"] != args.run_id], row], ignore_index=True), PROMOTIONS_FILE
    )

    log.info(
        "1-day QLIKE and VaR exceptions over the last %d days:\n%s",
        WINDOW,
        scores[["qlike", "n_exceptions", "zone"]].round(4),
    )
    verdict = "promoted" if decision["promoted"] else "kept"
    log.info(
        "%s %s: challenger %s QLIKE %.4f (%s) against champion %s QLIKE %.4f (%s)",
        verdict,
        decision["champion_after"],
        decision["challenger"],
        decision["challenger_qlike"],
        decision["challenger_zone"],
        decision["champion_before"],
        decision["champion_qlike"],
        decision["champion_zone"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
