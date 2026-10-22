import mlflow
import numpy as np
import pandas as pd
import pytest

from pipeline import config, promotion, registry, var
from pipeline.book import BOOK_NOTIONAL

DAYS = pd.bdate_range("2025-01-01", periods=300)


def scores(**rows: tuple[float, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {model: {"qlike": qlike, "n_exceptions": 0, "zone": zone} for model, (qlike, zone) in rows.items()}
    ).T.astype({"qlike": float, "n_exceptions": int})


def test_a_challenger_with_lower_loss_and_the_same_zone_is_promoted():
    decision = promotion.decide(
        scores(gjr=(1.60, "green"), garch=(1.55, "green"), ewma=(1.70, "green")), "gjr"
    )
    assert (
        decision["challenger"] == "garch" and decision["promoted"] and decision["champion_after"] == "garch"
    )


def test_a_challenger_with_a_worse_zone_is_not_promoted_even_with_lower_loss():
    decision = promotion.decide(
        scores(gjr=(1.60, "green"), garch=(1.55, "yellow"), ewma=(1.70, "green")), "gjr"
    )
    assert not decision["promoted"] and decision["champion_after"] == "gjr"


def test_the_champion_stays_when_no_challenger_has_a_lower_loss():
    decision = promotion.decide(
        scores(gjr=(1.50, "yellow"), garch=(1.55, "green"), ewma=(1.70, "green")), "gjr"
    )
    assert decision["challenger"] == "garch" and not decision["promoted"]


def test_scores_count_the_exceptions_of_each_candidate_on_the_last_window():
    variance = pd.Series(1.0, index=DAYS)  # 1% daily volatility: VaR of 2.326% of the book
    pnl = pd.Series(0.0, index=DAYS)
    pnl.iloc[[-3, -20, -40]] = -0.03 * BOOK_NOTIONAL  # three losses of 3% inside the window
    pnl.iloc[10] = -0.05 * BOOK_NOTIONAL  # outside the 250-day window
    table = promotion.score_candidates(pnl, {"gjr": variance}, window=250)
    assert table.at["gjr", "n_exceptions"] == 3 and table.at["gjr", "zone"] == "green"
    assert table.at["gjr", "last_day"] == DAYS[-2]  # the last day has no next day yet
    next_squared = (pnl / BOOK_NOTIONAL * 100) ** 2
    days = DAYS[-251:-1]
    ratio = next_squared.shift(-1).loc[days].where(lambda s: s > 0) / 1.0
    assert table.at["gjr", "qlike"] == pytest.approx((ratio - np.log(ratio) - 1).mean())


def test_the_registry_starts_with_gjr_and_follows_a_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MLFLOW_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.chdir(tmp_path)  # MLflow writes run artifacts under the working directory
    assert registry.champion() == "gjr"
    models = registry.client()
    mlflow.set_experiment("test")
    with mlflow.start_run() as run:
        mlflow.log_dict({"model_id": "garch"}, "decision.json")
    registry.promote(models, "garch", run.info.run_id, f"{run.info.artifact_uri}/decision.json")
    assert registry.champion() == "garch"


def test_the_parametric_champion_uses_the_registry_model():
    pnl = pd.Series(
        np.random.default_rng(0).normal(0, 50_000, 900), index=pd.bdate_range("2011-01-03", periods=900)
    )
    variances = {
        name: pd.Series(level, index=pnl.index)
        for name, level in [("ewma", 1.0), ("garch", 4.0), ("gjr", 9.0)]
    }
    table = var.build_fact_var(pnl, variances, champion="garch").set_index(["method_id", "for_date"])
    garch, champion = table.loc["param_garch", "var_99_eur"], table.loc["param_champion", "var_99_eur"]
    pd.testing.assert_series_equal(garch, champion, check_names=False)
