"""The whitespace gate must stay wired and pass on a clean working-tree diff."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci_check_whitespace.py"


def test_whitespace_script_exists() -> None:
    assert SCRIPT.is_file()


def test_whitespace_check_exits_zero_on_current_diff() -> None:
    # Local/CI without GITHUB_BASE_SHA: git diff --check on unstaged + staged.
    # Fails this pack if we introduce trailing whitespace or conflict markers.
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=REPO_ROOT, check=False)
    assert result.returncode == 0
