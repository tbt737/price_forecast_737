# PSD_COUNTRY_GRAIN_HARDENING — báo cáo (local, chưa push / chưa ghi DB)

- Base: commit `0152103` + verdict **AUDIT_FAIL** đã khóa (country collapse + provenance collision = blocker P0).
- Phạm vi đúng pack được duyệt: config + connector + tests + chạy lại dry-run audit. **Không** ingest, push, MV/cutover, production write.
- Bằng chứng chạy lại: `reports/psd_liquid_dry_run_audit_full.txt` và `reports/psd_liquid_dry_run_audit.json` (đã được ghi đè bằng kết quả **sau hardening**; kết quả FAIL trước đó được bảo lưu trong `reports/psd_liquid_dry_run_audit_report.md`).

## VERDICT chạy lại: **AUDIT_PASS** — grain/provenance collision = 0 (PIT vẫn là blocker riêng)

## 1. Thay đổi

### Config (`configs/ingestion/sources.yaml`)
- `country_code` (mã PSD) **bắt buộc** cho mọi metric: khai báo mức series, override được mức metric.
- `region_code` (mã `dim_region` của ta) đi kèm — cần vì PSD dùng `CH`=China, `VM`=Vietnam trong khi profiles dùng `CN`/`VN`.
- Mapping đã chốt (xác minh trên bulk thật, cột "npos" = số market year có giá trị dương):

| Series | Metric | PSD country | region_code | npos |
|---|---|---|---|---|
| CORN | cả 3 roles | US | US | 67/67 |
| WHEAT | cả 3 roles | US | US | 67/67 |
| SOYBEAN | cả 3 roles | US | US | 63/63 (imports 40/63 — nhiều năm Mỹ không nhập, zero hợp lệ) |
| RICE | cả 3 roles | TH | TH | 67/67 (imports 25/67 — Thái hầu như không nhập, zero hợp lệ) |
| SUGAR | import_volume | **CH** | CN | 66/67 — nước mua lớn nhất |
| SUGAR | inventory | **IN** | IN | 67/67 — nước quản lý tồn kho lớn nhất |
| ROBUSTA | 3 metrics legacy | VM | VN | 66/66 cho attr 28/88/178 |

- SUGAR thiết kế **từng role một country** đúng yêu cầu (Brazil bị loại cho imports vì npos=5/67 — không có tín hiệu).
- ROBUSTA (regression): ghim VM/VN — trước đây cùng khiếm khuyết collapse.

### Loader (`etl/ingestion/config.py`)
- `SupplyDemandSpec.country_for(metric)` / `region_for(metric)`: metric-override → series default → **raise** nếu thiếu (fail-closed ngay khi load config).
- `SupplyDemandMetricDetail` thêm `country_code` / `region_code` tùy chọn.

### Validator (`etl/ingestion/validate_psd.py`)
- Mỗi metric phải resolve được country; duplicate `(usda_commodity_id, attribute_id, country)` giữa các series = lỗi (grain collision ở mức config).
- Guard "commodity vắng khỏi PSD bulk" giờ đọc từ catalog (mọi entry có `usda_commodity_id: null`), không hardcode tên commodity.

### Connector (`etl/sources/supply_demand/usda_psd_bulk.py`)
- Lọc CSV theo `(Attribute_ID, Country_Code)` — chỉ đúng **một quốc gia** cấu hình cho mỗi metric.
- Ghi `region_code` vào record (grain writer không còn `region_key = NULL`) và thêm country vào payload hash.
- `source_record_id` = `<src>:<usda_id>:<period>_<attr>_<country>` — provenance hết trùng.
- Fail-closed: (a) metric thiếu country → raise lúc build map; (b) country cấu hình **không có dòng nào** trong CSV → raise liệt kê `commodity/metric@country`; (c) grain output trùng (cùng commodity/metric/country/period xuất hiện 2 lần) → raise thay vì emit mơ hồ; (d) hai series map cùng `(usda_id, attr, country)` → raise.

## 2. Tests (tất cả chạy thật)

- `tests/quality/test_usda_psd_liquid_config.py`: mapping country ghim đúng theo pack; load fail khi thiếu `country_code`; fixture đa quốc gia (decoy AF/BR/VM) → decoy bị loại, **grain + provenance collision = 0** cả theo khóa connector lẫn khóa writer `(commodity, region, metric, period_start)`.
- `tests/integration/test_noaa_usda_connectors.py` (regression ROBUSTA): chỉ dòng VM được emit (dòng BR bị loại), `region_code='VN'`, `source_record_id` có hậu tố `_VM`, id không trùng; fail-closed cho: CSV rỗng, không dòng khớp, country cấu hình vắng mặt (`@ID`), country không cấu hình, grain trùng.
- Toàn suite: **411 passed, 1 skipped** (skip = cần Postgres). `ruff` sạch, `mypy` sạch trên 3 module sửa.

## 3. Chạy lại dry-run audit (bulk thật, 2 090 920 dòng — read-only)

- Tham chiếu tiền-hardening: nếu bỏ qua country, 92 997/99 294 rows (93,7%) va chạm — connector mới phải tránh và đã tránh.
- Mọi `(commodity, metric, country)` cấu hình đều tồn tại trong bulk với chuỗi năm liên tục (bảng mục 1).
- Collect hardened: **926 records** (thay vì 99 294 đổ vào 6 297 khóa), `gate_rejected=0`, **provenance collision = 0**, **writer-grain collision = 0**, regions = `{US: 591, TH: 201, CN: 67, IN: 67}`.
- Guards giữ nguyên: SUGAR không `mechanistic_ready`; COCOA vẫn excluded.

## 4. Còn nguyên (không thuộc pack này)

- **PIT blocker riêng**: `release_date = ingest date` ⇒ 0/5 fold lịch sử nhìn thấy driver. Sửa country grain **không** làm mechanistic sẵn sàng; cần pack tái dựng vintage theo `releaseMonth` (duyệt riêng) hoặc chờ ~252 phiên hậu-ingest.
- Chưa ingest/push/MV/cutover/production write nào được thực hiện.
- `etl/sources/supply_demand/usda_psd.py` (connector API cũ, không được `build_connectors` dùng cho supply_demand) chưa được harden — nêu để theo dõi nếu có ai kích hoạt lại.
