"""The volatility model of the parametric VaR, kept in the MLflow model registry.

The registered model `var-volatility` gets a version each time a model is promoted, and the alias
`champion` points to the current one. Until the first promotion run, the champion is GJR-GARCH, the
choice of the volatility study.
"""

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from pipeline import config

REGISTERED_MODEL = "var-volatility"
ALIAS = "champion"
CANDIDATES = ("ewma", "garch", "gjr")  # the 1-day forecasts the VaR stage computes
DEFAULT_CHAMPION = "gjr"
SHORT_NAMES = {"ewma": "EWMA", "garch": "GARCH", "gjr": "GJR"}
LONG_NAMES = {"ewma": "EWMA", "garch": "GARCH(1,1)", "gjr": "GJR-GARCH"}


def client() -> MlflowClient:
    mlflow.set_tracking_uri(config.MLFLOW_URI)
    return MlflowClient()


def registered_champion(registry: MlflowClient) -> str | None:
    try:
        version = registry.get_model_version_by_alias(REGISTERED_MODEL, ALIAS)
    except MlflowException:
        return None  # nothing registered yet
    return version.tags["model_id"]


def champion() -> str:
    return registered_champion(client()) or DEFAULT_CHAMPION


def promote(registry: MlflowClient, model_id: str, run_id: str, artifact_uri: str) -> str:
    """Register a new version for the model, point the champion alias to it, return the version."""
    try:
        registry.get_registered_model(REGISTERED_MODEL)
    except MlflowException:
        registry.create_registered_model(
            REGISTERED_MODEL, description="1-day volatility forecast of the book used by the parametric VaR"
        )
    version = registry.create_model_version(
        REGISTERED_MODEL, source=artifact_uri, run_id=run_id, tags={"model_id": model_id}
    )
    registry.set_registered_model_alias(REGISTERED_MODEL, ALIAS, version.version)
    return version.version
