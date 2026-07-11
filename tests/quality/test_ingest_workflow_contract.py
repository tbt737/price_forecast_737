"""Contract test for the daily ingest workflow (VN-PRICE-1D).

Pins the non-blocking guarantees so a future edit can't silently make VN prices
critical or break the futures feed / freshness gate. Parses the YAML (no network,
no CI trigger)."""

from __future__ import annotations

from pathlib import Path

import yaml

_WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ingest.yml"


def _steps() -> list[dict]:
    wf = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    return wf["jobs"]["ingest"]["steps"]


def _with_run(steps: list[dict], sub: str) -> list[dict]:
    return [s for s in steps if isinstance(s.get("run"), str) and sub in s["run"]]


def test_vn_prices_step_present_and_non_blocking() -> None:
    steps = _steps()
    vn = _with_run(steps, "--sources vn_prices")
    assert len(vn) == 1, "expected exactly one vn_prices ingest step"
    step = vn[0]
    run = step["run"]
    # Conflict-safe: the backfill path (per-record ON CONFLICT DO NOTHING), NOT the
    # all-or-nothing --write batch that could roll back a today-only source's rows.
    assert "--backfill --sources vn_prices" in run
    assert "--write" not in run
    # Daily top-up of the forecast-primary SJC series so GOLD_VN can grow past MIN_HISTORY.
    assert "--sources vn_history --history-days 7" in run
    assert step.get("continue-on-error") is True  # its failure must not fail the job
    assert str(step.get("if")).strip() == "always()"  # runs even if a prior step failed
    assert "${{ secrets.DATABASE_URL }}" in (step.get("env", {}) or {}).get("DATABASE_URL", "")


def test_vn_stocks_step_present_non_blocking_and_flag_gated() -> None:
    steps = _steps()
    vn = _with_run(steps, "--sources vn_stocks")
    assert len(vn) == 1, "expected exactly one vn_stocks ingest step"
    step = vn[0]
    run = step["run"]
    # Restatement-aware reconcile (etl/restatement.py): anchor-check + append at the
    # latest revision + atomic revision-bump reload — NOT the append-only backfill
    # path, which silently drops a restated (adjusted) history. The CLI is dry-run by
    # default, so the scheduled step passes --write explicitly.
    assert "--reconcile --sources vn_stocks" in run
    assert "--history-days 10" in run
    assert "--write" in run
    assert "--backfill" not in run  # append-only path is banned for this source
    assert step.get("continue-on-error") is True  # a dead chart API must not fail the job
    # 🔒 Owner decision 2026-07-11: the step is OFF unless the repo variable is
    # explicitly 'true' — an append-only top-up of a restating (adjusted) source is
    # unsafe until the revision-aware heal lands (unlock criteria in PLAN.md §5).
    # Owner observation 3: `!cancelled()` (independent step: self-heals after an
    # unrelated failure, but never fires on a cancelled run) — NOT `always()`.
    cond = str(step.get("if"))
    assert "!cancelled()" in cond
    assert "always()" not in cond
    assert "vars.ENABLE_VN_STOCKS_INGEST == 'true'" in cond  # ONLY when opted in
    assert "${{ secrets.DATABASE_URL }}" in (step.get("env", {}) or {}).get("DATABASE_URL", "")


def test_futures_price_step_stays_critical() -> None:
    steps = _steps()
    fut = _with_run(steps, "--sources prices")
    crit = [s for s in fut if "--backfill" in s["run"] and "vn_prices" not in s["run"]]
    assert len(crit) == 1, "expected the critical futures backfill step"
    # Critical = NOT continue-on-error (a real failure must fail the job).
    assert crit[0].get("continue-on-error") is not True
    assert "if" not in crit[0]  # runs unconditionally as the gating first data step


def test_freshness_gate_still_present() -> None:
    steps = _steps()
    gate = _with_run(steps, "check_freshness.py")
    assert len(gate) == 1 and str(gate[0].get("if")).strip() == "always()"
    # The gate must not have been coupled to VN prices.
    assert "vn_prices" not in gate[0]["run"]


def test_ml_feature_refresh_step_present_and_non_blocking() -> None:
    steps = _steps()
    refresh = _with_run(steps, "refresh_ml_features.py")
    assert len(refresh) == 1, "expected a post-ingest MV refresh step"
    step = refresh[0]
    assert "--write" in step["run"]
    assert step.get("continue-on-error") is True
    assert str(step.get("if")).strip() == "always()"
    assert "${{ secrets.DATABASE_URL }}" in (step.get("env", {}) or {}).get("DATABASE_URL", "")
