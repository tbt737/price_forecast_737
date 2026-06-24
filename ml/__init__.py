"""Forecasting: transparent baseline (Fourier + trend) with walk-forward backtest.

Deterministic and config-agnostic — no per-commodity hardcoding. The baseline
fits log-price = linear trend + annual Fourier harmonics by ordinary least
squares (numpy), forecasts 30/90 trading days ahead, and is evaluated honestly
out-of-sample against a naive (last-value) benchmark.
"""
