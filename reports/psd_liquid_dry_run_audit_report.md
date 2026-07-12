# PSD-LIQUID-DRY-RUN-AUDIT — báo cáo (read-only)

> **Cập nhật:** verdict FAIL dưới đây đã được xử lý bởi pack `PSD_COUNTRY_GRAIN_HARDENING`
> (xem `reports/psd_country_grain_hardening_report.md`). `psd_liquid_dry_run_audit_full.txt`
> và `.json` hiện phản ánh lần chạy lại **sau hardening** (AUDIT_PASS).

- Base: commit `0152103` (config-only). Nguồn: `psd_alldata_csv.zip` (2 090 920 dòng, cache 2026-07-12).
- Không có thao tác ghi DB / MV / push / backfill nào được thực hiện.
- Chi tiết đầy đủ theo commodity × country × attribute × market year: `reports/psd_liquid_dry_run_audit_full.txt`; tóm tắt máy đọc: `reports/psd_liquid_dry_run_audit.json`. Script tái lập: `scripts/psd_liquid_dry_run_audit.py`.

## VERDICT: **FAIL** (2 blocker, 1 cảnh báo) — không được cấp quyền ingest với connector hiện tại

## 1. Coverage & cardinality (PASS về dữ liệu nguồn)

| Commodity | Countries | Rows/attr | MY span | Ghi chú |
|-----------|-----------|-----------|---------|---------|
| CORN | 145 | 7 586 | 1960–2026 | planted_area npos=100% ở benchmark |
| WHEAT | 145 | 7 754 | 1960–2026 | Russia chỉ từ MY 1987 |
| SOYBEAN | 98 | 3 808 | 1964–2026 | Brazil/Argentina từ MY 1977 |
| RICE | 138 | 7 616 | 1960–2026 | inventory nhiều nước npos=0 (chỉ nước lớn có) |
| SUGAR | 194 | 9 501 | 1960–2026 | planted_area không tồn tại (đúng catalog) |

- **Unit**: nhất quán tuyệt đối — `(1000 HA)` cho planted_area, `(1000 MT)` cho imports/ending stocks; khớp catalog `0152103`. PASS.
- **Duplicate trong CSV** theo (commodity, country, MY, attribute): **0**. PASS.
- **Missing years** trong span của từng nước: 0 (chuỗi năm liên tục). PASS.
- **Zero-value**: nhiều (ví dụ CORN inventory Afghanistan npos=0/67) — zero là giá trị hợp lệ của PSD (nước không tồn kho), không phải missing; chỉ thành vấn đề nếu chọn nhầm nước làm chuỗi đại diện.

## 2. Country semantics — **FAIL (blocker #1: country collapse)**

- PSD bulk **không có dòng World aggregate** cho 5 commodity này (`world_aggregate_present=False` ở mọi attribute).
- Connector `UsdaPsdBulkSource` hiện **không lọc và không ghi country**: mọi nước cùng đổ vào một grain `(commodity, metric, period_start)` với `region_key = NULL`.
- Mô phỏng ghi: **92 997 / 99 294 records (93,7%) va chạm grain** → `ON CONFLICT DO NOTHING` giữ lại **một dòng tùy ý theo thứ tự CSV** cho mỗi (commodity, metric, năm). Chuỗi kết quả sẽ là dữ liệu của một quốc gia ngẫu nhiên, vô nghĩa về kinh tế.
- **Blocker #2 (provenance):** `source_record_id = <src>:<commodity>:<period>_<attr>` bỏ qua country → 92 997 id trùng nhau mang giá trị khác nhau — vi phạm nguyên tắc id định danh ổn định.
- Ghi chú: series ROBUSTA hiện hữu dùng cùng connector nên **cũng mang khiếm khuyết này** (ngoài phạm vi pack, nêu để theo dõi).

## 3. Tác động PIT của `release_date = ingest date` — WARN (định lượng)

- MY span 1960–2026 nhưng mọi record nhận `release_date` = ngày ingest.
- Walk-forward production (folds=5, min_train=252) đặt toàn bộ cut trong quá khứ ⇒ **0/5 fold (0%) nhìn thấy bất kỳ giá trị driver nào**. `mechanistic_fourier_supply` không thể được đánh giá trên lịch sử.
- Hai lối thoát (đều cần duyệt riêng): (a) chờ ~252 phiên hậu-ingest (~1 năm giao dịch); (b) pack tái dựng vintage theo `releaseMonth` của PSD API (giữ đúng bản phát hành lịch sử).

## 4. Guards

- SUGAR: chỉ imports/inventory, **không** `mechanistic_ready` (planted_area vắng trong PSD — xác nhận trên dữ liệu thật). PASS.
- COCOA: không có trong config; không có commodity Cocoa/Cacao trong bulk. PASS.
- Dry-run collect + provenance gate: 99 294 records, gate reject 0 (cấu trúc record hợp lệ; lỗi nằm ở ngữ nghĩa grain, không phải format).

## 5. Đề xuất mapping country cụ thể (chờ duyệt — chưa sửa gì)

Nguyên tắc: **một chuỗi = một quốc gia benchmark**, khai báo trong config (`country_code` trên mỗi series), connector lọc `Country_Code` và đưa country vào cả grain lẫn `source_record_id`. Không tự cộng gộp nhiều nước (cộng gộp = pack riêng nếu muốn "world synthetic").

| Commodity | Đề xuất chính | Căn cứ (coverage đã xác minh) | Dự phòng |
|-----------|---------------|-------------------------------|----------|
| CORN | `US` | 67/67 năm dương cả 3 role; Mỹ là anchor giá CBOT ZC | BR, AR, CH |
| WHEAT | `US` | 67/67 cả 3 role; RS chỉ từ 1987 | CA, AS, RS |
| SOYBEAN | `US` | 63/63 planted+inventory; anchor CME ZS | BR (từ 1977), AR, CH |
| RICE | `TH` hoặc `VM` | TH: 67/67 planted+inventory (benchmark xuất khẩu); VM: inventory chỉ 32/67 dương | IN, US |
| SUGAR | `BR` (inventory) + cân nhắc `CH`/`IN` (imports) | BR imports npos=5/67 (Brazil hầu như không nhập — đúng ngữ nghĩa); nếu cần chuỗi imports có tín hiệu, dùng CH (66/67) hoặc IN (41/67) | TH |

Khuyến nghị RICE: chọn **TH** (Thailand) làm chính vì đủ cả planted_area + inventory dương 67/67; VM inventory quá thưa.

## Điều kiện mở khóa ingest (đề xuất, cần pack riêng)

1. Thêm `country_code` vào schema series trong `sources.yaml` + `SupplyDemandSpec`; connector lọc đúng một nước, ghi `region_code`/country vào record + provenance key.
2. Test: collision = 0 sau lọc; source_record_id duy nhất; đúng nước được chọn.
3. Quyết định riêng cho PIT (chờ tích lũy vs tái dựng releaseMonth).
