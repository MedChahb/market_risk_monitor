"""Measure the anomaly detector on errors injected into the real Yahoo closes.

With a fixed seed, 200 errors of each type are placed at random dates and series, at least 7 sessions
apart on a series: one-day spikes, frozen prices, decimal shifts, unadjusted splits, missing days and
futures-roll jumps. Each layer is scored by its recall per error type and its precision: the quality
rules (stale values, missing sessions), the robust z-score detector, an Isolation Forest fitted on the
real data, and the production detector (rules and robust z-score). A flag counts when it falls on a
wrong day or the session after it. The ten largest real moves are checked for false alarms. Rebuilt at
every run, after the transform stage.
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest

from pipeline import anomalies, config, db, quality, raw
from pipeline.catalog import get

log = logging.getLogger("anomaly_evaluation")

ERROR_TYPES = ("spike", "frozen", "decimal_shift", "split", "missing_days", "roll_jump")
N_PER_TYPE = 200
SEED = 2  # seed 1 was used to choose the detector's settings; this one only measures it
WARM_UP = 260  # sessions of history before the first error on a series
SPACING = 6  # sessions kept free on each side of an error on the same series
FOREST_BUDGETS = (0.001, 0.01)  # share of real series-days the Isolation Forest may flag
N_TOP_MOVES = 10
Cells = set[tuple[pd.Timestamp, str]]


def inject(
    clean: dict[str, pd.Series], seed: int, n_per_type: int = N_PER_TYPE
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """Copies of the closes with errors placed at random; one row per error with the days it affects."""
    rng = np.random.default_rng(seed)
    data = {instrument: values.copy() for instrument, values in clean.items()}
    taken = {instrument: set() for instrument in clean}
    errors = []
    for kind in ERROR_TYPES:
        placed = 0
        while placed < n_per_type:
            instrument = str(rng.choice(sorted(clean)))
            days = clean[instrument].index
            position = int(rng.integers(WARM_UP, len(days) - 10))
            if taken[instrument] & set(range(position - SPACING, position + SPACING + 1)):
                continue
            taken[instrument] |= set(range(position - SPACING, position + SPACING + 1))
            values, day, length = data[instrument], days[position], 1
            if kind == "spike":
                values.loc[day] *= 1 + rng.uniform(0.05, 0.20) * rng.choice([-1, 1])
            elif kind == "decimal_shift":
                values.loc[day] *= rng.choice([10.0, 0.1])
            elif kind == "frozen":
                length = int(rng.integers(3, 6))
                values.loc[days[position : position + length]] = values.loc[days[position - 1]]
            elif kind == "split":
                values.loc[day:] /= 2
            elif kind == "roll_jump":
                values.loc[day:] *= 1 + rng.uniform(0.02, 0.06) * rng.choice([-1, 1])
            else:
                length = int(rng.integers(1, 4))
                data[instrument] = values.drop(days[position : position + length])
            cells = list(days[position : position + length + 1])  # the wrong days and the session after
            errors.append({"error_type": kind, "instrument": instrument, "date": day, "cells": cells})
            placed += 1
    return data, pd.DataFrame(errors)


def rule_flags(data: dict[str, pd.Series]) -> Cells:
    flags = set()
    for instrument, values in data.items():
        series = get(instrument)
        for found in (quality.check_missing_days(values, series), quality.check_stale(values, series)):
            flags |= {(day, instrument) for day in found["date"]}
    return flags


def tick_flags(data: dict[str, pd.Series]) -> Cells:
    found = anomalies.detect_ticks(data)
    return set(zip(found["date"], found["instrument"], strict=True))


def forest_flags(forest: IsolationForest, threshold: float, data: dict[str, pd.Series]) -> Cells:
    features = anomalies.forest_features(data)
    scores = forest.score_samples(features.to_numpy())
    return set(features.index[scores < threshold])


def score(flags: Cells, errors: pd.DataFrame) -> dict:
    """Precision of the flags and recall per error type."""
    error_cells = [{(day, row.instrument) for day in row.cells} for row in errors.itertuples()]
    caught = pd.Series([bool(cells & flags) for cells in error_cells], index=errors.index)
    every_cell = set().union(*error_cells)
    precision = len(flags & every_cell) / len(flags) if flags else np.nan
    recall = caught.groupby(errors["error_type"]).mean().reindex(ERROR_TYPES)
    return {
        "n_flags": len(flags),
        "precision": precision,
        **{f"recall_{kind}": recall[kind] for kind in ERROR_TYPES},
    }


def evaluate(clean: dict[str, pd.Series], seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scores per layer on injected errors, and the layers that flag the largest real moves."""
    data, errors = inject(clean, seed)
    real_features = anomalies.forest_features(clean)
    forest = IsolationForest(n_estimators=300, random_state=0).fit(real_features.to_numpy())
    real_scores = forest.score_samples(real_features.to_numpy())
    layers = {
        "Rules: stale, missing sessions": (rule_flags(data), rule_flags(clean)),
        "Robust z-score": (tick_flags(data), tick_flags(clean)),
    }
    for budget in FOREST_BUDGETS:
        threshold = np.quantile(real_scores, budget)
        layers[f"Isolation Forest, {budget * 100:g}% budget"] = (
            forest_flags(forest, threshold, data),
            forest_flags(forest, threshold, clean),
        )
    rules, ticks = layers["Rules: stale, missing sessions"], layers["Robust z-score"]
    layers["Production: rules + z-score"] = (rules[0] | ticks[0], rules[1] | ticks[1])

    table = pd.DataFrame(
        [
            {"layer_order": order, "layer": layer, **score(injected, errors)}
            for order, (layer, (injected, _)) in enumerate(layers.items())
        ]
    ).assign(n_per_type=N_PER_TYPE, seed=seed)

    returns = anomalies.log_returns(clean)
    z = returns.apply(anomalies.robust_z)
    largest = returns.abs().stack().sort_values(ascending=False).head(N_TOP_MOVES).index
    top_moves = pd.DataFrame(
        {
            "date": largest.get_level_values(0),
            "instrument_id": largest.get_level_values(1),
            "log_return": [returns.at[cell] for cell in largest],
            "robust_z": [z.at[cell] for cell in largest],
            "flagged_by": [
                ", ".join(layer for layer, (_, real) in layers.items() if cell in real) or "none"
                for cell in largest
            ],
        }
    )
    return table, top_moves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the anomaly detector on injected errors.")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    load_dotenv()

    yahoo, path = raw.read_latest(config.RAW_DIR, "yahoo")
    if yahoo is None:
        log.error("no raw Yahoo file in %s: nothing evaluated", config.RAW_DIR)
        return 1
    table, top_moves = evaluate(anomalies.price_series(yahoo), args.seed)
    with db.engine().begin() as conn:
        db.run_sql_file(conn, "anomalies.sql")
        db.insert(conn, "gold", "fact_anomaly_evaluation", table)
        db.insert(conn, "gold", "fact_anomaly_top_moves", top_moves)

    log.info("%s, seed %d, %d errors of each type", path.name, args.seed, N_PER_TYPE)
    shown = table.set_index("layer")[["n_flags", "precision", *(f"recall_{kind}" for kind in ERROR_TYPES)]]
    log.info("precision and recall by layer:\n%s", shown.round(3).to_string())
    for layer in table["layer"]:
        n_flagged = int(top_moves["flagged_by"].str.contains(layer, regex=False).sum())
        log.info("%-45s flags %d of the %d largest real moves", layer, n_flagged, len(top_moves))
    return 0


if __name__ == "__main__":
    sys.exit(main())
