# Kế hoạch sửa chữa & nâng cấp vận hành (2026-09-13)

> **For agentic workers:** chạy từng pack theo `.claude/loop-profile.md`.
> Luồng song song: pack **VN30-RETRY** giao Grok (Cursor Grok / Grok Build CLI).
> Các pack còn lại tuần tự, pack nào có ghi production thì **duyệt trước khi làm**.

**Goal:** Sửa các lỗ ingest/ML đang fail-soft trên production, rồi mới đọc evidence forecast (ACC-REVIEW) và polish.

**Architecture:** Không thêm commodity-hardcode. Mọi thay đổi keyed trên `commodity_code` / config YAML. Ingest vẫn fail-closed; bước `continue-on-error` không được che lỗi hàng loạt.

**Tech stack:** GitHub Actions ingest, `etl/restatement.py`, Entrade chart API, FastAPI `cqp-api`, Next.js `cqp-web`, Supabase Postgres, `scripts/canonicalize_ml_feature_mv.py`.

**App live:**
- Web: https://cqp-web-402296591988.asia-northeast1.run.app
- API: https://cqp-api-402296591988.asia-northeast1.run.app
- Repo: https://github.com/tbt737/price_forecast_737

## Global constraints

- INV-1 config-over-code; INV-3 zero look-ahead; INV-7 writes opt-in.
- Không `--write` / migrate / deploy production nếu owner chưa duyệt trong session.
- Baseline test không giảm. Không nới `min_reload_coverage` xuống dưới 0.9.
- Nông sản Ấn Độ đứng 2026-04-20 là **thiết kế** (không có mandi live) — không bịa feed.
- Van der Pol / volatility gate / meta-blend: **không làm lại**.

---

## Hiện trạng đã đo (13/9/2026, Chủ nhật)

| Tín hiệu | Kết quả |
|---|---|
| Daily ingest cron 22:00 UTC | 50/50 success từ 25/7 |
| Freshness futures | OK — latest **2026-09-11** (phiên Thứ Sáu) |
| Freshness `vn_domestic` | OK — latest **2026-09-12** |
| Freshness `vn_stocks` | OK — latest **2026-09-11** |
| VN30 reconcile 12/9 | **18 appended, 12 error** (`window fetch yielded no usable bars`) |
| MV refresh | **CONTRACT_VIOLATION** — `mv_ml_daily_features_wide` là TABLE (`relkind=r`) |
| Accuracy writer | success sau mỗi ingest |
| Live `/stats` | 66 profiles / 114 instruments / 464 056 fact rows (docs pin 52 — lệch inventory) |
| GOLD_VN SJC | 174/252 ngày, last 2026-09-11 |
| Produce Ấn Độ (Agmarknet) | last **2026-04-20** — snapshot, không ingest live |

12 mã lỗi 12/9: `MSN_VN MWG_VN PLX_VN SAB_VN SHB_VN SSB_VN VHM_VN VIB_VN VIC_VN VJC_VN VNM_VN VPB_VN`.

`ENABLE_VN_STOCKS_INGEST` **đã bật** (bước reconcile chạy trên cron) — `PLAN.md` §5 còn ghi OFF, cần sync.

---

## Thứ tự pack (an toàn production → data → accuracy → polish)

### Pack 0 — PLAN-SYNC (docs, không ghi DB) — luồng này

Cập nhật `PLAN.md` cho khớp production: ingest VN30 đang ON, inventory live 66, GOLD_VN 174, MV refresh đỏ, 12 ticker error. Trỏ tới file này.

**Done khi:** `PLAN.md` §3 phản ánh thứ tự dưới; không đổi code.

---

### Pack 1 — VN30-RETRY — **landed on this branch** (`3722c20`)

**Vấn đề:** Entrade trả cửa sổ rỗng cho ~12/30 mã; `_fetch_records` không retry → ticker đó `error` cả ngày. Job vẫn xanh vì `continue-on-error`.

**Files:**
- Modify: `etl/restatement.py` (`_fetch_records`, nhánh empty ~L190)
- Modify: `etl/sources/market/vn_stocks.py` (`_http_fetch` / `collect`)
- Test: `tests/integration/test_restatement.py`

**Hành vi:** 3 lần thử / ticker (1 + 2 retry), backoff ngắn, sleep injectable (=0 trong test). Hết retry vẫn `error` + warning cũ. Không hardcode ticker.

**Gates:**
```
python -m ruff check etl/restatement.py etl/sources/market/vn_stocks.py tests/integration/test_restatement.py
python -m pytest tests/integration/test_restatement.py -q
```

**Không làm:** không `--write` prod; không bỏ `continue-on-error` cho đến khi retry có test.

**Verify sau merge (owner duyệt dispatch):** một lần `ingest.yml` thủ công ngày phiên HOSE; kỳ vọng `error` giảm về 0 hoặc còn lỗi lẻ không theo cụm 12.

---

### Pack 2 — INGEST-SIGNAL (visibility)

**Vấn đề:** Job Daily ingestion xanh trong khi VN30 `ok:false` và MV refresh exit 1.

**Files:**
- Modify: `.github/workflows/ingest.yml` (step tóm tắt / fail-soft annotation)
- Test: `scripts/ci_check_workflows.py` + test workflow contract nếu có

**Hành vi:** In ra một dòng `INGEST_PARTIAL_FAIL` với counts; **không** đổi freshness gate futures. Cân nhắc: comment trên run, không fail cả job (VN stocks vẫn non-critical).

**Không làm:** không biến VN30 thành critical (Tết sẽ đỏ oan).

---

### Pack 3 — MV-CANONICALIZE — **cần duyệt ghi production**

**Vấn đề:** `scripts/refresh_ml_features.py --write` từ chối vì relation là TABLE pandas, không phải MATERIALIZED VIEW. Script canonicalize **đã có**.

**Files / lệnh (đã viết sẵn):**
- `scripts/canonicalize_ml_feature_mv.py`
- Runbook: `docs/ml/feature_view_refresh_runbook.md`

**Sequence (hai lệnh, hai lần duyệt):**
```
python scripts/canonicalize_ml_feature_mv.py --prepare-candidate
# owner đọc parity / coverage
python scripts/canonicalize_ml_feature_mv.py --cutover
```

**Done khi:** ingest step Refresh ML feature view exit 0 trên cron; `relkind=m` + unique index `uq_mv_ml_daily_features_wide`.

---

### Pack 4 — ACC-REVIEW — **read-only**

Writer từ 2026-07-05; h=30 đã quá 6 tuần. Evaluator Monday xanh. `PLAN.md` vẫn WAITING — có thể đã có hàng `evaluated`.

**Làm:** SQL trong `docs/ml/accuracy-loop-runbook.md` (read-only trên prod). Distill MAPE theo commodity/horizon vào `.claude/loop-memory.md`. **Không** bịa số.

**Cần:** `DATABASE_URL` (owner chạy hoặc duyệt session đọc).

---

### Pack 5 — RESTATE-COVERAGE

AUDIT-1B: `min_reload_coverage == 0.9` chấp nhận reload cắt 10% lịch sử. Pin hiện tại: `tests/integration/test_restatement.py:411`.

**Files:**
- `etl/ingestion/config.py` default / `configs/ingestion/sources.yaml` `vn_stocks.reconcile.min_reload_coverage`
- Test: `tests/integration/test_restatement.py`

**Hành vi:** mặc định **1.0**; test coverage 0.90 phải **fail**; happy-path 100% vẫn pass.

**Điều kiện:** làm **trước** khi tin restatement full-basket. Không cần ghi prod nếu chỉ đổi ngưỡng cho lần reconcile sau.

---

### Pack 6 — FORECAST-REVISION (đường serve live)

`ml/forecast.py` lấy `MAX(revision)` theo (commodity, instrument), không theo ngày. AUDIT-1B: cùng class lỗi `build_pandas_mv` từng HIGH.

**Files:**
- `ml/forecast.py` ~L85-102
- Twin: API `/prices` nếu cùng pattern
- Test: `apps/api/tests/test_revision_reads.py` + `ml/tests` nếu có

**Hành vi:** mỗi `price_date` lấy revision mới nhất (single-basis theo ngày), không cắt đuôi ngày chỉ tồn tại ở revision cũ hơn max toàn series.

---

### Pack 7 — FRESHNESS-PRODUCE (config)

8/52 mã không thuộc freshness group (produce Ấn Độ + dehydrated*). Forecast UI hiện như series tươi.

**Files:**
- `configs/ingestion/sources.yaml` `monitoring.groups`
- `scripts/check_freshness.py` (nếu cần cờ `frozen: true`)
- Test: freshness unit tests

**Hành vi:** nhóm `produce_frozen` với `max_gap_days` lớn **hoặc** status `frozen` (không STALE đỏ). UI badge “snapshot 2026-04-20” — chỉ nếu pack UI nhỏ, không bắt buộc cùng PR.

---

### Pack 8 — DOCS-INVENTORY

Live 66 profiles vs test pin 52. Đo lại: `tests/quality/test_profiles_quality.py` vs `/stats`. Nếu DB có profile không có YAML → ghi rõ, không bịa YAML. Cập nhật README/ARCHITECTURE counts từ test pin, ghi chú live delta.

---

## Việc thủ công (owner, GitHub UI)

- [ ] Branch protection `master`: checks đúng tên `Python (lint + tests)` và `Web (lint + test + build)`.
- [ ] Đóng/merge PR #3 (nội dung đã vào AUDIT-1) và PR #2 draft (chồng polish).
- [ ] Telegram secrets cho weekly movers nếu muốn bản tin live (WEEKLY-MOVERS-1D).
- [ ] Pack 3 + mọi `--write` prod: duyệt từng bước.

**Không làm từ agent:** Skills Loop optimizer (LOCKED); Next.js 16; RESEARCH-PUBLISH-1.

## Việc không đụng

- GOLD_VN chờ 252 ngày — chỉ theo dõi.
- USDA PSD ingest giữ OFF.
- NOAA ONI skip: monitoring, không blocker giá.
- Produce Ấn Độ: không invent live mandi.

---

## Grok Build CLI (luồng song song trên máy bạn)

Cloud Agent VM **không** có binary `grok` và không có self-hosted worker. Pack 1 đã giao Cursor Grok trên cùng branch. Nếu bạn muốn **Grok Build CLI** làm pack khác (Pack 5 hoặc 6), kích hoạt trên máy local:

**Repo:** https://github.com/tbt737/price_forecast_737

```bash
curl -fsSL https://x.ai/cli/install.sh | bash   # Windows: irm https://x.ai/cli/install.ps1 | iex
cd /path/to/price_forecast_737
git checkout cursor/ops-repair-plan-92ba
grok
```

Prompt dán: `docs/plans/2026-09-13-grok-build-handoff.md`. Cần SuperGrok / X Premium Plus, hoặc `export XAI_API_KEY=xai-...`.

---

## Execution

1. Pack 0 (file này + `PLAN.md`) — agent hiện tại.
2. Pack 1 — Grok song song.
3. Pack 2 sau khi Pack 1 có test (tránh đổi workflow 2 lần).
4. Pack 3 chỉ khi owner duyệt ghi DB.
5. Pack 4 read-only ngay khi có `DATABASE_URL`.
6. Pack 5–8 theo sức, không nhảy Next.js 16.
