"""ETL source adapters.

Phase 3A ships STUB adapters only: each declares its fact family and a
``collect()`` that returns no records (no network, no credentials, no ingestion).
Real connectors are implemented in a later phase.
"""

from etl.sources.base import BaseSource

__all__ = ["BaseSource"]
