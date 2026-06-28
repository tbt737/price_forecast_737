"""Research-only candidate pool for Phase 8A OU evaluation.

This is a LOCAL/BACKTEST comparison harness — it is deliberately separate from the
production forecaster (``ml/forecast.py``) and the guarded runner
(``ml/runner.py``), so adding the OU candidate here changes no production default.
It mirrors the production best-of rule (pick the lowest-MAPE candidate, but only
leave the naive benchmark when it is cleared by ``SWITCH_MARGIN``) so that
``best_of`` and ``best_of + OU`` are compared like-for-like.

Pure functions over (dates, values); no DB, no network, no import-time side
effects. Callers supply the price series (e.g. a read-only scratchpad loader)."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from ml.backtests.walk_forward import walk_forward_ar, walk_forward_gbm, walk_forward_ou
from ml.models.gbm_forecaster import is_available as gbm_available

# Mirror the production best-of margin (ml/forecast.py SWITCH_MARGIN) so the
# research comparison uses the same bar to beat.
SWITCH_MARGIN = 0.02


def best_of(
    candidate_mapes: dict[str, float], naive_mape: float, *, margin: float = SWITCH_MARGIN
) -> tuple[str, float]:
    """Production-equivalent selection: lowest finite MAPE wins, but only displaces
    naive when it beats it by ``margin``. Returns ``(chosen_name, effective_mape)``."""
    finite = {k: v for k, v in candidate_mapes.items() if np.isfinite(v)}
    if not finite:
        return ("naive", naive_mape)
    best = min(finite, key=lambda k: finite[k])
    if np.isfinite(naive_mape) and finite[best] < naive_mape * (1.0 - margin):
        return (best, finite[best])
    return ("naive", naive_mape)


def evaluate_commodity(
    dates: list[date],
    values: np.ndarray,
    *,
    horizon: int,
    folds: int = 5,
    min_train: int = 252,
    exog_features: np.ndarray | None = None,
    include_gbm: bool = True,
) -> dict[str, Any]:
    """Walk-forward every candidate and report naive, each model, best-of and
    best-of+OU. All folds are time-ordered and leakage-safe (see walk_forward)."""
    ar = walk_forward_ar(
        dates, values, horizon=horizon, folds=folds, min_train=min_train, exog_features=exog_features
    )
    naive_mape = ar.naive_mape
    candidates: dict[str, float] = {"ridge_ar": ar.model_mape}

    if include_gbm and gbm_available():
        gb = walk_forward_gbm(
            dates, values, horizon=horizon, folds=folds, min_train=min_train, exog_features=exog_features
        )
        candidates["gbm"] = gb.model_mape
        gbc = walk_forward_gbm(
            dates,
            values,
            horizon=horizon,
            folds=folds,
            min_train=min_train,
            use_cycles=True,
            exog_features=exog_features,
        )
        candidates["gbm_cyc"] = gbc.model_mape

    ou = walk_forward_ou(dates, values, horizon=horizon, folds=folds, min_train=min_train)
    ou_mape = ou.model_mape

    base_choice, base_mape = best_of(candidates, naive_mape)
    with_ou = {**candidates, "ou": ou_mape}
    ou_choice, ou_mape_best = best_of(with_ou, naive_mape)

    return {
        "folds": ar.folds,
        "naive_mape": naive_mape,
        "candidates": candidates,
        "ou_mape": ou_mape,
        "best_of": {"choice": base_choice, "mape": base_mape, "edge": _edge(naive_mape, base_mape)},
        "best_of_plus_ou": {"choice": ou_choice, "mape": ou_mape_best, "edge": _edge(naive_mape, ou_mape_best)},
        "ou_alone_edge": _edge(naive_mape, ou_mape),
    }


def _edge(naive_mape: float, model_mape: float) -> float:
    """Edge = naive_MAPE - model_MAPE (positive ⇒ model beats naive)."""
    if not (np.isfinite(naive_mape) and np.isfinite(model_mape)):
        return float("nan")
    return float(naive_mape - model_mape)
