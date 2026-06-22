"""Fixture-backed ETL source — reads tiny LOCAL JSON files (no network, no writes).

A `FixtureSource` reads a deterministic JSON fixture under ``etl/fixtures/`` and
yields `NormalizedRecord`s. It is read-only and sandboxed:

* the resolved path must stay inside the fixture root (rejects ``..`` traversal
  and absolute paths that escape the root);
* only ``.json`` is accepted (``.yaml``/``.yml`` only if PyYAML is already a
  dependency — it is, via the loader — and always through ``yaml.safe_load``);
* malformed JSON raises a clear `FixtureError`;
* it cannot write or insert anything.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"  # etl/fixtures
_ALLOWED_SUFFIXES = {".json", ".yaml", ".yml"}


class FixtureError(ValueError):
    """Raised for unsafe paths, unsupported extensions, or malformed fixtures."""


def _safe_path(path: str | Path, root: Path) -> Path:
    root = root.resolve()
    candidate = (root / Path(path)).resolve()  # absolute `path` overrides root, then guarded below
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FixtureError(f"Fixture path escapes fixture root {root}: {path!r}") from exc
    if candidate.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise FixtureError(f"Unsupported fixture extension: {candidate.suffix!r}")
    if not candidate.is_file():
        raise FixtureError(f"Fixture not found: {candidate}")
    return candidate


def _parse(text: str, suffix: str, name: str) -> list:
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FixtureError(f"Malformed JSON in fixture {name}: {exc}") from exc
    else:  # .yaml/.yml — safe_load only
        import yaml

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # pragma: no cover - JSON is the default
            raise FixtureError(f"Malformed YAML in fixture {name}: {exc}") from exc
    if not isinstance(data, list):
        raise FixtureError(f"Fixture {name} must contain a JSON/YAML list of records")
    return data


class FixtureSource(BaseSource):
    """Reads a local fixture file and emits NormalizedRecords for one family."""

    def __init__(
        self,
        family: FactFamily,
        path: str | Path,
        *,
        source_code: str = "manual",
        root: Path = FIXTURE_ROOT,
    ) -> None:
        self.family = family
        self.source_code = source_code
        self._path = _safe_path(path, root)

    def collect(self) -> Iterable[NormalizedRecord]:
        rows = _parse(self._path.read_text(encoding="utf-8"), self._path.suffix.lower(), self._path.name)
        return [NormalizedRecord.from_dict(self.family, row) for row in rows]


def load_family_fixture(family: FactFamily, *, root: Path = FIXTURE_ROOT) -> FixtureSource:
    """Convenience: the canonical ``<family>.json`` fixture for a family."""
    return FixtureSource(family, f"{family.value}.json", root=root)


def all_family_fixtures(*, root: Path = FIXTURE_ROOT) -> list[FixtureSource]:
    return [load_family_fixture(fam, root=root) for fam in FactFamily]
