# PSD_CONNECTOR_PATH_UNIFICATION — báo cáo gates (local, chưa push / chưa ghi DB)

- Base: `5c78d4d` (FEASIBILITY_FAIL / FORWARD-ONLY đã khóa). Không ingest, push, MV/cutover, production write.
- Hệ quả forward-only được tôn trọng nguyên vẹn: `release_date` = thời điểm ingest thực; không dùng `Calendar_Year/Month` làm historical release; không tái dựng revision; SUGAR vẫn ngoài triad.

## 1. Connector API cũ: DISABLED fail-closed

`etl/sources/supply_demand/usda_psd.py` được thay bằng stub fail-closed:

- `UsdaPsdSource(...)` **raise ngay tại constructor** (và cả `collect()`) với thông điệp nêu rõ lý do: đường API có trước contract country-grain (không lọc country, không có country trong provenance, unit hardcode `"1000 bags"`), endpoint nó dùng không nằm trong swagger chính thức, và không có API key để xác minh bản viết lại. Muốn bật lại phải có pack riêng được duyệt.
- Toàn bộ code mạng (`urllib`) bị gỡ khỏi file; file đồng thời bị **rút khỏi `NETWORK_EXEMPT`** trong `tests/quality/test_etl_contracts.py` — nếu ai thêm lại network code vào đường API mà chưa qua pack hardening, gate genericity/network sẽ fail ngay.
- Chọn disable thay vì harden vì không thể xác minh đường API: không có `USDA_FAS_API_KEY`, mọi request trả 403, và response API không mang country dimension (kết luận audit `5c78d4d`).

## 2. Không đường nào trong `build_connectors` tạo được record PSD thiếu country

- `build_connectors(which="supply_demand")` chỉ tạo đúng **một** connector: `UsdaPsdBulkSource` (khẳng định bằng test mới, so sánh `type(...) is`).
- Chuỗi fail-closed nhiều lớp: (a) `load_ingestion_config` raise nếu metric nào thiếu country; (b) `UsdaPsdBulkSource` raise khi build map nếu country không resolve được; (c) country cấu hình không có dòng CSV nào → raise; (d) mọi record đều mang `region_code` + country trong `source_record_id`.
- Siết thêm trong pack này: **unit là contract** — nếu CSV upstream đổi unit so với unit đã khai (catalog-validated), connector raise `"unit drift"` thay vì emit lẫn magnitude; unit trên record lấy từ dòng nguồn, bỏ hẳn default hardcode `"1000 MT"`.

## 3. Regression tests mới (tất cả chạy thật)

| Test | Bảo vệ |
|---|---|
| `test_usda_api_connector_is_disabled_fail_closed` | Constructor + collect của đường API cũ raise |
| `test_build_connectors_psd_path_is_bulk_only_with_full_country_grain` | Chỉ bulk connector; mọi metric resolve country + region |
| `test_usda_bulk_connector_fails_closed_on_unit_drift` | CSV đổi unit `(MT)` ≠ config `(1000 HA)` → raise |
| `test_usda_bulk_connector_source_id_and_unit_contract` | `source_record_id` = `manual:0440000:2024-09-01_4_US` (country embedded), unit từ nguồn, region trên record, qua gate |
| (giữ từ pack trước) country collapse / duplicate grain / missing country / ROBUSTA VM | Không hồi quy |

## 4. Full gates (mirror `make quality`, chạy thật ngày 12-07-2026)

| Gate | Kết quả |
|---|---|
| `python -m compileall etl scripts apps tests ml db apply_views.py` | exit 0 |
| `python -m ruff check .` | All checks passed |
| `python -m mypy -p app` | 0 lỗi / 28 files |
| `python -m mypy etl` | 0 lỗi / 34 files |
| `python -m pytest` | **551 passed, 1 skipped** (skip duy nhất = cần PostgreSQL thật) |
| `python scripts/ci_check_workflows.py` | OK (5 workflows) |

## 5. Audit bulk chạy lại (read-only, bulk thật 2 090 920 dòng)

- **AUDIT_PASS**: collect 926 records, `gate_rejected=0`, provenance collision = 0, writer-grain collision = 0, regions `{US: 591, TH: 201, CN: 67, IN: 67}`.
- Ghi chú PIT trong audit script được cập nhật theo verdict đã khóa: bỏ nhánh "releaseMonth reconstruction" (đã bị bác ở `5c78d4d`), chỉ còn forward-only (~252 phiên hậu-ingest). WARN PIT 0/5 giữ nguyên — đây là blocker riêng, không thuộc pack này.

## 6. Trạng thái sau pack

- Mọi đường sinh record PSD đều đi qua contract hardened duy nhất (bulk); đường API cũ chết fail-closed từ constructor.
- Vẫn **chưa** cấp quyền push/ingest/MV/cutover/production write — pack dừng tại commit + báo cáo gates này.
