"""Portable column types shared across models."""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on PostgreSQL (indexable, binary); plain JSON elsewhere (e.g. SQLite tests).
JSONColumn = JSON().with_variant(JSONB(), "postgresql")
