"""Forecasting: Ridge autoregressive model with an honest walk-forward backtest.

Deterministic and config-agnostic — no per-commodity hardcoding (CLAUDE.md §1).
The primary model predicts the h-day-ahead log-return from point-in-time features
(momentum, mean-reversion, seasonality) via ridge regression, anchored to the
last price. It is evaluated out-of-sample against a naive (last-value) benchmark
and **falls back to that benchmark per-horizon whenever it can't beat it**, so the
forecast is never shown as better than the evidence supports. A damped-trend
Fourier baseline remains available for reference.
"""
