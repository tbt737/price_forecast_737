# VN-STOCKS restatement heal (RESTATE-1) — hồ sơ trình duyệt production

> Owner unlock-criteria gốc: `PLAN.md` §5 (VN30-PROD). Trạng thái từng tiêu chí ở §9
> dưới cùng. Module: `etl/restatement.py`; CLI: `python -m etl.ingest --reconcile
> --sources vn_stocks [--history-days N] [--write]` (dry-run mặc định — INV-7).

## 1. Quyết định kiến trúc — canonical series & revision

- **Cơ chế**: dùng đúng cột `revision` có sẵn trong unique grain của `fact_price_daily`
  (`commodity_key, market_instrument_key, price_date, revision`) — schema đã ghi rõ
  *"a revised series gets a new row, never an UPDATE"*. Không UPDATE, không DELETE.
- **Canonical series của một instrument** = toàn bộ dòng ở `max(revision)` của
  instrument đó (**revision theo SERIES, không theo từng ngày**) → không bao giờ lai
  basis cũ/mới. Các revision cũ giữ nguyên làm audit trail.
- **Phát hiện restatement**: reconcile hằng ngày fetch cửa sổ ngắn (10 ngày), so các
  ngày trùng (anchors, loại trừ hôm nay) với series canonical; lệch tương đối
  > `epsilon_pct` (0.5%) ở bất kỳ anchor nào ⇒ nguồn đã restate ⇒ refetch TOÀN BỘ
  lịch sử (`deep_from` 2000-01-01, một request duy nhất) và ghi trọn series ở
  `max(revision)+1` trong MỘT transaction.
- Anchors khớp ⇒ append thuần các ngày mới **ở đúng revision hiện hành** (không phải
  luôn rev 0). Không có dòng nào stored ⇒ `empty`, không ghi (deep backfill ban đầu là
  bước vận hành chủ động — step 8). Không có anchor trùng ⇒ `no_anchor`, không ghi.

## 2. Migration / schema

**KHÔNG cần migration.** `revision` + unique grain + `CHECK (revision >= 0)` đã có từ
`db/migrations/001_core_schema.sql`. Không bảng mới, không cột mới, không enum mới.

## 3. Cơ chế phát hiện / reconcile định kỳ

- Bước workflow hằng ngày (vẫn khóa sau `ENABLE_VN_STOCKS_INGEST`):
  `python -m etl.ingest --reconcile --sources vn_stocks --history-days 10 --write`
  — mỗi ngày đều là một lần reconcile đầy đủ: kiểm tra 5 anchors gần nhất rồi mới
  append; restatement được phát hiện muộn nhất là lần chạy kế tiếp sau corporate action.
- Đường `--backfill --sources vn_stocks` (append-only) từ nay CHỈ dùng cho lần nạp đầu
  trên kho rỗng (bị cấm trong workflow bằng contract test; sau khi một instrument đã
  có revision > 0, backfill rev-0 chỉ tạo dòng "vô hình" với mọi đường đọc — quy tắc
  vận hành: không chạy lại deep backfill sau khi đã có restatement; dùng reconcile).

## 4. Atomicity khi refresh từng mã

- Reload/append mỗi instrument = `session.add_all(...)` + **một** `commit()`; mọi
  exception ⇒ `rollback()` ⇒ không còn lại gì (test pin). **Không dùng
  ON CONFLICT DO NOTHING** trong reconcile — duplicate grain trong một reload là bug
  và phải nổ to (per-instrument, các mã khác tiếp tục).
- Guard chống reload cụt: `min_reload_coverage` (0.9) — series mới phải phủ ≥ 90% số
  ngày đang stored, kèm 0 record invalid; vi phạm ⇒ `error`, không ghi gì (giữ nguyên
  basis cũ). Chặn việc một response bị cắt ngắn trở thành series canonical.

## 5. Cache / model invalidation

- **Forecast cache** (`/commodities/{code}/forecast`): fingerprint =
  `(row count, max price_date, max revision)` trên toàn commodity — restatement
  bump revision ⇒ cache tự vô hiệu (kể cả khi max date không đổi).
- **Restatement `release_date`**: mỗi dòng ở revision mới mang
  `release_date = ngày reconcile` (vẫn `>= observation_date`). As-of views /
  backtests trước ngày đó vẫn thấy revision cũ; live latest-revision reads thấy
  basis mới ngay.
- **`mv_ml_daily_features_wide`**: workflow ingest gọi
  `scripts/refresh_ml_features.py --write` (non-blocking) sau các bước ghi.
  Lưu ý: view PIT nền chọn revision mới nhất THEO TỪNG NGÀY với
  `release_date <= as_of_date`; chuỗi giá FIT model đọc qua
  `ml.forecast.load_price_series` (revision theo series — single basis).

## 6. Tests (17 test mới cho pack này; tổng suite 467)

- `tests/integration/test_restatement.py` (10): mô phỏng **chia cổ tức 15% restate
  toàn bộ lịch sử** + **tách 2:1 lần hai** (revision 1 → 2, đơn điệu); append +
  idempotent rerun; dry-run không ghi; empty/no-anchor fail-closed; reload cụt bị từ
  chối; duplicate-date trong response không tạo duplicate grain; jump bất thường chỉ
  cảnh báo; config từ sources.yaml.
- `apps/api/tests/test_revision_reads.py` (1): endpoint prices chỉ trả revision mới
  nhất (không lẫn 1 giá trị basis cũ, không duplicate ngày).
- Kiểm tra NaN/Infinity: gate ở parser (`test_parse_chart_arrays_rejects_non_finite_closes`).
- Concurrent ingest: cùng-payload rerun idempotent (SQLite); race thật giữa 2 writer
  được chặn bởi unique grain của Postgres — một bên IntegrityError ⇒ rollback toàn bộ
  instrument ⇒ lần chạy sau tự lành. (Test concurrency thật cần PG — cùng cơ chế
  `tests/integration/test_daily_conflicts.py`, chạy khi có `CQP_TEST_PG_URL`.)

## 7. Full gates (2026-07-11)

`pytest 467 passed + 1 skipped` · `vitest 39` · `ruff 0` · `mypy 0 (28 app + 33 etl)` ·
`ci_check_workflows OK` · 2 architecture guards xanh (restatement.py không network —
connector vẫn là biên mạng duy nhất). Sim-to-real: dry-run trên prod thật → 30/30
`empty`, 0 ghi; canary SQLite dữ liệu thật (FPT 626 dòng): reconcile ×2 → `fresh`/
`fresh`, kho bất biến.

## 8. Kế hoạch canary production (đề xuất — cần owner duyệt riêng từng bước)

1. Bật đường ghi cho MỘT lần chạy tay (không bật flag cron): canary 2 mã FPT_VN,
   VCB_VN — `--backfill --sources vn_stocks --history-days 5400` giới hạn 2 endpoint
   (tạm thời comment 28 endpoint còn lại trong sources.yaml của nhánh chạy, hoặc chạy
   script bơm qua `backfill(connectors=[...])` với 2 spec).
2. Truy vấn kiểm chứng (read-only) sau canary:
   - `SELECT count(*), count(DISTINCT price_date), min/max(price_date) FROM fact_price_daily WHERE ...` từng mã;
   - duplicate grain: `GROUP BY instrument, price_date, revision HAVING count(*)>1` → 0 dòng;
   - discontinuity: max |return ngày| ≤ ~7% trừ ngày có corporate action đã biết;
   - reconcile dry-run ngay sau đó phải trả `fresh` cho 2 mã.
3. Chạy lại reconcile lần 2 (hội tụ/idempotent — kỳ vọng `fresh`, 0 dòng mới).
4. Rollback canary nếu hỏng: `DELETE FROM fact_price_daily WHERE market_instrument_key
   IN (2 mã) ` trong transaction (chỉ 2 mã, chưa hệ thống nào phụ thuộc) — cần owner
   duyệt riêng như mọi thao tác xóa.
5. Đạt ⇒ backfill đủ 30 mã → lặp bước 2 → deploy API → smoke → deploy web → smoke
   `/stocks` → bật `ENABLE_VN_STOCKS_INGEST=true` → theo dõi ≥1 chu kỳ cron.

## 9. Đối chiếu 6 tiêu chí owner

| # | Tiêu chí | Trạng thái |
|---|---|---|
| 1 | Ingest sau cập nhật được lịch sử bị restate, không ON CONFLICT DO NOTHING cùng revision | ✅ revision-bump reload, add_all + commit, không conflict suppression |
| 2 | Re-run cùng payload idempotent | ✅ test `fresh` + store bất biến (synthetic + real-data canary) |
| 3 | Không có chuỗi lai basis cũ/mới | ✅ single-basis rule ở cả 2 đường đọc + test API/ML |
| 4 | Test mô phỏng cổ tức/tách CP restate toàn bộ lịch sử | ✅ 15% dividend + 2:1 split (rev 1 → 2) |
| 5 | Duplicate grain / NaN / revision / jump bất thường | ✅ unique-grain abort test, parser NaN gate, revision đơn điệu, jump warning |
| 6 | Full gates xanh | ✅ §7 |
