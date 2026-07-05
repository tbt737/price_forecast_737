"""Contract test for the dedicated VN freshness monitor workflow (ETL-VN-4).

Pins the guarantees that make it a safe monitor: it is READ-ONLY (never ingests or
writes), it is scoped to the vn_domestic group with --strict (so VN staleness turns it
red), and it runs on a schedule + manual dispatch. Parses the YAML only — no network,
no CI trigger."""

from __future__ import annotations

from pathlib import Path

import yaml

_WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "vn-freshness-monitor.yml"


def _wf() -> dict:
    return yaml.safe_load(_WF.read_text(encoding="utf-8"))


def _run_commands(wf: dict) -> str:
    steps = wf["jobs"]["vn-freshness"]["steps"]
    return "\n".join(s["run"] for s in steps if isinstance(s.get("run"), str))


def test_monitor_workflow_exists_and_parses() -> None:
    assert _WF.exists(), "vn-freshness-monitor.yml must exist"
    wf = _wf()
    assert "vn-freshness" in wf["jobs"]


def test_monitor_is_scheduled_and_dispatchable() -> None:
    wf = _wf()
    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1); accept either.
    triggers = wf.get(True, wf.get("on"))
    assert isinstance(triggers, dict)
    assert "schedule" in triggers, "monitor must run on a schedule (cron)"
    assert "workflow_dispatch" in triggers, "monitor must be manually dispatchable"


def test_monitor_runs_vn_scoped_strict_gate() -> None:
    run = _run_commands(_wf())
    assert "check_freshness.py" in run
    assert "--group vn_domestic" in run  # scoped to VN, not coupled to futures
    assert "--strict" in run  # VN stale ⇒ this workflow red


def test_monitor_is_read_only_no_ingest() -> None:
    run = _run_commands(_wf())
    # Must never ingest or write — it is a read-only SELECT max(price_date) gate.
    assert "etl.ingest" not in run
    assert "--write" not in run
    assert "--backfill" not in run


def test_monitor_uses_database_url_secret_and_not_on_push() -> None:
    wf = _wf()
    steps = wf["jobs"]["vn-freshness"]["steps"]
    gate = [s for s in steps if isinstance(s.get("run"), str) and "check_freshness.py" in s["run"]]
    assert len(gate) == 1
    assert "${{ secrets.DATABASE_URL }}" in (gate[0].get("env", {}) or {}).get("DATABASE_URL", "")
    # A monitor should not fire on every push/PR — only schedule + manual.
    triggers = wf.get(True, wf.get("on"))
    assert "push" not in triggers and "pull_request" not in triggers
