"""Fail if the current git range introduces trailing whitespace or conflict markers.

Uses ``git diff --check`` so historical research docs with trailing spaces are not
retroactively gated. Locally checks unstaged + staged diffs; in GitHub Actions
checks the PR/push range (``GITHUB_BASE_SHA`` / ``GITHUB_EVENT_BEFORE``).
"""

from __future__ import annotations

import os
import subprocess


def _run(args: list[str]) -> int:
    result = subprocess.run(args, check=False)
    return result.returncode


def main() -> int:
    base = (os.environ.get("GITHUB_BASE_SHA") or "").strip()
    before = (os.environ.get("GITHUB_EVENT_BEFORE") or "").strip()
    zero = "0" * 40

    if base:
        return _run(["git", "diff", "--check", base, "HEAD"])
    if before and before != zero:
        return _run(["git", "diff", "--check", before, "HEAD"])
    # Local / unknown CI context: only the working tree + index (clean checkout = no-op).
    return _run(["git", "diff", "--check"]) or _run(["git", "diff", "--cached", "--check"])


if __name__ == "__main__":
    raise SystemExit(main())
