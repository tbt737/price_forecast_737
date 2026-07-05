"""Contract test for the accuracy-loop workflows (ACC-2).

Pins the guarantees that make the scheduled loop safe:
- the WRITER chains off a *successful* daily ingest + is manually dispatchable, runs the
  writer with --write, and has a real exit code (no continue-on-error);
- the EVALUATOR runs weekly + is manually dispatchable, runs the evaluator with --write;
- neither workflow ingests prices, migrates, or runs on push/PR;
- the only DB mutation the two scripts perform is against fact_forecast_log.

Parses YAML + reads the scripts' SQL constants — no network, no CI trigger, no DB.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WF = _ROOT / ".github" / "workflows"
sys.path.insert(0, str(_ROOT / "scripts"))


def _wf(name: str) -> dict:
    return yaml.safe_load((_WF / name).read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1); accept either.
    t = wf.get(True, wf.get("on"))
    assert isinstance(t, dict)
    return t


def _run_blob(wf: dict, job: str) -> str:
    steps = wf["jobs"][job]["steps"]
    return "\n".join(s["run"] for s in steps if isinstance(s.get("run"), str))


# ── writer ───────────────────────────────────────────────────────────────────
def test_writer_chains_off_successful_ingest_and_dispatch() -> None:
    wf = _wf("accuracy-writer.yml")
    t = _triggers(wf)
    assert t.get("workflow_run", {}).get("workflows") == ["Daily ingestion"]
    assert "workflow_dispatch" in t
    assert "push" not in t and "pull_request" not in t
    job = wf["jobs"]["write-forecast-log"]
    # Only after a successful ingest (or a manual dispatch).
    guard = str(job.get("if", ""))
    assert "workflow_run.conclusion == 'success'" in guard
    assert "workflow_dispatch" in guard


def test_writer_runs_writer_with_write_and_real_exit_code() -> None:
    wf = _wf("accuracy-writer.yml")
    run = _run_blob(wf, "write-forecast-log")
    assert "scripts/write_forecast_log.py --write" in run
    step = next(s for s in wf["jobs"]["write-forecast-log"]["steps"] if "write_forecast_log.py" in str(s.get("run")))
    assert step.get("continue-on-error") is not True  # a real failure must fail the job
    assert "${{ secrets.DATABASE_URL }}" in (step.get("env", {}) or {}).get("DATABASE_URL", "")
    assert "|| true" not in run  # no swallowed exit code


# ── evaluator ────────────────────────────────────────────────────────────────
def test_evaluator_is_weekly_and_dispatchable() -> None:
    wf = _wf("accuracy-evaluator.yml")
    t = _triggers(wf)
    crons = [c.get("cron") for c in t.get("schedule", [])]
    assert any(c and c.split()[-1] in {"1", "MON"} for c in crons), f"expected a weekly (Monday) cron, got {crons}"
    assert "workflow_dispatch" in t
    assert "push" not in t and "pull_request" not in t


def test_evaluator_runs_evaluator_with_write() -> None:
    wf = _wf("accuracy-evaluator.yml")
    run = _run_blob(wf, "evaluate-forecast-log")
    assert "scripts/evaluate_forecast_log.py --write" in run
    step = next(
        s for s in wf["jobs"]["evaluate-forecast-log"]["steps"] if "evaluate_forecast_log.py" in str(s.get("run"))
    )
    assert step.get("continue-on-error") is not True
    assert "${{ secrets.DATABASE_URL }}" in (step.get("env", {}) or {}).get("DATABASE_URL", "")


# ── both: no ingest / migration in either workflow ───────────────────────────
def test_accuracy_workflows_never_ingest_or_migrate() -> None:
    pairs = (("accuracy-writer.yml", "write-forecast-log"), ("accuracy-evaluator.yml", "evaluate-forecast-log"))
    for name, job in pairs:
        run = _run_blob(_wf(name), job)
        assert "etl.ingest" not in run
        assert "alembic" not in run and "migrat" not in run.lower()


# ── both: the only DB mutation is fact_forecast_log ──────────────────────────
def test_scripts_mutate_only_fact_forecast_log() -> None:
    import evaluate_forecast_log as ev
    import write_forecast_log as wr

    write_sql = [wr.INSERT_SQL, ev.UPDATE_EVALUATED_SQL, ev.UPDATE_EXPIRED_SQL]
    mutated: set[str] = set()
    for sql in write_sql:
        mutated |= {m.group(1) for m in re.finditer(r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", sql, re.I)}
    assert mutated == {"fact_forecast_log"}, f"unexpected write target(s): {mutated}"
    # And there is no DELETE anywhere in the write path.
    assert not any(re.search(r"\bDELETE\b", s, re.I) for s in write_sql)
