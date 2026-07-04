import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
VIEWS_DIR = PROJECT_ROOT / "db" / "views"
GENERATED_FILE = VIEWS_DIR / "generated" / "010_mv_ml_daily_features_wide.sql"
SCALAR_VIEW_SQL = VIEWS_DIR / "001_v_ml_daily_feature_events_long.sql"
JSONB_VIEW_SQL = VIEWS_DIR / "002_v_ml_daily_features_jsonb.sql"
COMPILER_SCRIPT = VIEWS_DIR / "compile_ml_feature_views.py"


@pytest.mark.integration
def test_compiler_generates_valid_sql():
    """Compiler output must define the wide MV with safe metric aliases."""
    assert GENERATED_FILE.exists(), "Compiled SQL file must exist"

    with open(GENERATED_FILE, encoding="utf-8") as f:
        content = f.read()

    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ml_daily_features_wide" in content
    assert "jsonb_path_query_first" in content
    assert "v_ml_daily_feature_scalar" in content

    alias_matches = re.findall(r"AS ([a-zA-Z0-9_]+),?$", content, re.MULTILINE)

    assert len(alias_matches) > 0, "No metrics found in the generated SQL"
    assert "price_close" in alias_matches, "price_close is a required baseline metric"

    for alias in alias_matches:
        assert re.match(r"^[a-z0-9_]+$", alias), f"Invalid alias found: {alias}"


@pytest.mark.integration
def test_scalar_view_enforces_deterministic_grain():
    """Scalar collapse must use DISTINCT ON with explicit tie-break ordering."""
    content = SCALAR_VIEW_SQL.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW v_ml_daily_feature_scalar" in content
    assert "DISTINCT ON (as_of_date, commodity_key, metric_code)" in content
    assert "region_key NULLS FIRST" in content
    assert "instrument_key NULLS FIRST" in content
    assert "observation_date DESC" in content
    assert "release_date DESC" in content
    assert "source_fact_id DESC" in content


@pytest.mark.integration
def test_jsonb_view_aggregates_scalar_layer():
    """JSONB aggregation must read scalar events, not raw long events."""
    content = JSONB_VIEW_SQL.read_text(encoding="utf-8")

    assert "FROM v_ml_daily_feature_scalar" in content
    assert "FROM v_ml_daily_feature_events_long" not in content


@pytest.mark.integration
def test_compiler_regeneration_is_deterministic():
    """Re-running the compiler must produce identical SQL output."""
    before = GENERATED_FILE.read_text(encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(COMPILER_SCRIPT)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0

    after = GENERATED_FILE.read_text(encoding="utf-8")
    assert after == before, "Compiler output changed on re-run; expected deterministic output"