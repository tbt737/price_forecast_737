"""Static check: every GitHub Actions workflow under .github/workflows/ must be valid YAML
with the minimal shape (a top-level ``jobs`` mapping). Fails non-zero on the first bad file
so ``make quality`` / CI catches a malformed workflow before it is pushed. No network, no writes."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def main() -> int:
    files = sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))
    if not files:
        print("[workflows] no workflow files found — nothing to check.")
        return 0
    bad = 0
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"[workflows] INVALID YAML — {path.name}: {exc}", file=sys.stderr)
            bad += 1
            continue
        if not isinstance(data, dict) or "jobs" not in data:
            print(f"[workflows] MALFORMED — {path.name}: missing top-level 'jobs' mapping", file=sys.stderr)
            bad += 1
            continue
        print(f"[workflows] OK — {path.name} ({len(data.get('jobs') or {})} job(s))")
    if bad:
        print(f"[workflows] {bad} invalid workflow file(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
