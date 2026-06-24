"""Automated ingestion: config-driven real-source connectors + orchestration.

Connectors fetch from real external sources (Yahoo Finance prices, NASA POWER
weather), map rows to ``NormalizedRecord``s with deterministic provenance, and
flow through the existing fail-closed pipeline (gate → write_batch). No source
symbols are hardcoded — everything is read from ``configs/ingestion/sources.yaml``.
"""
