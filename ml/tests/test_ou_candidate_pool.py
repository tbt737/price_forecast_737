"""Phase 8B — OU participates in the production candidate pool only through the
guarded best-of selector. These tests pin the gating contract (DB-free): the naive
benchmark and the 2% margin rule are intact, OU can win only when it clears the
margin, a weak OU never changes the outcome, and the disable hook exists.
"""

from __future__ import annotations

import inspect

from ml.forecast import OU_ENABLED, SWITCH_MARGIN, forecast_commodity, select_candidate


def test_ou_wins_when_it_beats_the_pool_by_margin() -> None:
    choice, mape = select_candidate({"ridge_ar": 9.0, "gbm": 8.5, "ou": 7.0}, naive_mape=8.0)
    assert choice == "ou" and mape == 7.0


def test_ou_rejected_when_weak_other_candidate_wins() -> None:
    # OU is in the pool but worse than ridge ⇒ ridge wins, OU is not chosen.
    choice, _ = select_candidate({"ridge_ar": 7.0, "ou": 9.5}, naive_mape=8.0)
    assert choice == "ridge_ar"


def test_naive_holds_when_nothing_clears_the_margin() -> None:
    # Best candidate is within 2% of naive ⇒ the benchmark holds.
    choice, _ = select_candidate({"ridge_ar": 7.95, "ou": 7.90}, naive_mape=8.0)
    assert choice == "naive"


def test_weak_ou_never_changes_the_outcome() -> None:
    # Adding a poor OU to the pool must not alter the selection (it can only ever help).
    without_ou = select_candidate({"ridge_ar": 7.0, "gbm": 7.5}, naive_mape=8.0)
    with_weak_ou = select_candidate({"ridge_ar": 7.0, "gbm": 7.5, "ou": 12.0}, naive_mape=8.0)
    assert without_ou == with_weak_ou


def test_margin_rule_is_intact() -> None:
    assert SWITCH_MARGIN == 0.02
    threshold = 8.0 * (1.0 - SWITCH_MARGIN)  # = 7.84
    assert select_candidate({"ou": threshold}, 8.0)[0] == "naive"  # equal ⇒ not strictly better
    assert select_candidate({"ou": threshold - 1e-6}, 8.0)[0] == "ou"  # just clears the margin


def test_empty_or_nonfinite_pool_falls_back_to_naive() -> None:
    assert select_candidate({}, 8.0)[0] == "naive"
    assert select_candidate({"ou": float("nan")}, 8.0)[0] == "naive"


def test_naive_held_when_naive_mape_is_nonfinite() -> None:
    # Without a usable naive MAPE the selector cannot prove an improvement ⇒ stays naive.
    assert select_candidate({"ou": 5.0}, float("nan"))[0] == "naive"


def test_enable_ou_hook_exists_and_default_on() -> None:
    sig = inspect.signature(forecast_commodity)
    assert "enable_ou" in sig.parameters  # config/test hook to disable OU
    assert sig.parameters["enable_ou"].default is OU_ENABLED
    assert OU_ENABLED is True  # wired into the production pool by default — still margin-gated
