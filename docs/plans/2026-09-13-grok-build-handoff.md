# Grok Build CLI — handoff prompt

Dùng trên máy local sau khi `grok` đã login. **Repo:** https://github.com/tbt737/price_forecast_737

**Đừng làm Pack 1** nếu Cursor Grok trên branch `cursor/ops-repair-plan-92ba` đã implement VN30-RETRY (tránh đụng file). Lấy pack tiếp theo chưa ai nhận: **Pack 5 RESTATE-COVERAGE** (ưu tiên) hoặc Pack 6 FORECAST-REVISION.

---

## Prompt dán vào `grok` (Pack 5 — RESTATE-COVERAGE)

```
Repo: https://github.com/tbt737/price_forecast_737
Read CLAUDE.md, PLAN.md, docs/plans/2026-09-13-ops-repair-upgrade.md Pack 5, etl/restatement.py (coverage guard ~L232-246), configs/ingestion/sources.yaml vn_stocks.reconcile, tests/integration/test_restatement.py.

AUDIT-1B confirmed: min_reload_coverage 0.9 accepts a reload that covers exactly 90% of stored dates, then bumps revision and drops the missing 10% from every read path.

Change default min_reload_coverage from 0.9 to 1.0 in config + StockReconcileConfig. Add/adjust a test that a 90% coverage reload is rejected (status error). Keep the three happy-path tests that republish 100%. Do not hardcode tickers. No production DB writes. Run:
  python -m pytest tests/integration/test_restatement.py -q
  python -m ruff check etl tests/integration/test_restatement.py
```

---

## Prompt dán vào `grok` (Pack 6 — FORECAST-REVISION) — chỉ khi Pack 5 xong hoặc tách branch

```
Repo: https://github.com/tbt737/price_forecast_737
ml/forecast.py load_price_series uses MAX(revision) for the whole (commodity, instrument) series. AUDIT-1B: same class of bug as build_pandas_mv (per-date latest revision). Fix so each price_date uses that date's latest revision, not a global max that can drop older dates. Tests in apps/api/tests/test_revision_reads.py. Config-over-code. No prod writes.
```

---

## Cài CLI

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
# Windows PowerShell:
# irm https://x.ai/cli/install.ps1 | iex
cd /path/to/price_forecast_737
git fetch origin
git checkout cursor/ops-repair-plan-92ba
grok
```

Auth: trình duyệt SuperGrok / X Premium Plus, hoặc `export XAI_API_KEY=xai-...`
