"""ML model-registry endpoints (Phase 7B).

Read-only: lists the JSON metadata written by the local backtest registry under
``data/models/`` and resolves the best registered model per commodity. Mounted only
behind the ``ENABLE_ML_MODELS_API`` flag (OFF by default) — see ``app.main``. No DB
writes; no network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(tags=["models"])

REGISTRY_DIR = Path(__file__).resolve().parents[4] / "data" / "models"

# Commodity codes are snake_case / uppercase identifiers. Constraining the path
# parameter to this set is defence-in-depth: it keeps user input out of the
# filesystem glob below (no '.', '/', '%' … ⇒ no path traversal, CWE-22).
_VALID_CODE = re.compile(r"[A-Z0-9_]{1,64}")

_BEST_MODEL_CACHE: dict[str, dict[str, Any]] = {}


@router.get("/models")
def list_models() -> list[dict[str, Any]]:
    """List all registered models (newest first). Empty if the registry is absent."""
    if not REGISTRY_DIR.exists():
        return []
    models: list[dict[str, Any]] = []
    for path in REGISTRY_DIR.glob("*.json"):
        try:
            models.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            continue  # skip unreadable/malformed registry files
    models.sort(key=lambda x: x.get("trained_at", ""), reverse=True)
    return models


@router.get("/commodities/{commodity_code}/models/best")
def get_best_model(commodity_code: str) -> dict[str, Any]:
    """Return the best registered model for a commodity, or 404 if none."""
    code = commodity_code.upper()
    if not _VALID_CODE.fullmatch(code):
        # Reject anything that is not a plain commodity code (blocks traversal into
        # the registry glob). Generic message — do not reflect the raw input.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No registered model found")
    if code in _BEST_MODEL_CACHE:
        return _BEST_MODEL_CACHE[code]

    from ml.registry.core import find_best_model

    try:
        best = find_best_model(code)
    except (OSError, ValueError, KeyError):
        best = None  # unreadable / malformed registry file ⇒ fail safe, no 500/leak
    if best is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No registered model found for '{code}'")
    res = best.to_dict()
    _BEST_MODEL_CACHE[code] = res
    return res
