# PSD_PIT_VINTAGE_FEASIBILITY_AUDIT — báo cáo (read-only)

- Base: `2f98ef5` (PSD_COUNTRY_GRAIN_HARDENING local PASS đã khóa). Không ghi DB, không ingest, không push.
- Script tái lập: `scripts/psd_pit_vintage_feasibility_audit.py`; log đầy đủ: `reports/psd_pit_vintage_feasibility_full.txt`; JSON: `reports/psd_pit_vintage_feasibility.json`.
- Đúng ràng buộc pack: **không suy diễn `release_date` từ market year** ở bất kỳ bước nào; mọi mốc thời gian dùng trong audit là metadata có thật trong dữ liệu (cột `Calendar_Year`+`Month` của bulk) hoặc bị đánh dấu "không có".

## VERDICT: **FEASIBILITY_FAIL → FORWARD-ONLY** — không dựng được vintage lịch sử đáng tin cậy; mechanistic lịch sử vẫn khóa

## 1. API: không có endpoint vintage được tài liệu hóa, và không thể probe sâu hơn

- Swagger chính thức của FAS OpenData (fetch 200, read-only) liệt kê đúng 9 endpoint PSD; **không có** endpoint `releaseYear/releaseMonth` nào — chỉ có `dataReleaseDates` (metadata lịch phát hành) và các endpoint dữ liệu lọc theo `commodity/country/marketYear` trả **bản mới nhất**.
- Cộng đồng (StackOverflow 2024) đồn một URL dạng `/world/year/{my}/releaseYear/{ry}/releaseMonth/{rm}` nhưng nó **không nằm trong swagger**; câu trả lời được chấp nhận nói API "chỉ nhận commodityCode và marketYear".
- Không thể xác minh bằng probe: **mọi** request `/api/psd/*` không có API key đều trả 403 — kể cả path bịa (`thisEndpointDoesNotExist` cũng 403), nên status code không phân biệt được endpoint tồn tại hay không. Môi trường này **không có `USDA_FAS_API_KEY`** (không có trong env/.env).
- Kể cả nếu endpoint đồn đại tồn tại: nó chỉ có biến thể `/world/` trong mọi nguồn đã thấy — không có bằng chứng nào cho vintage **theo country**, thứ mà grain đã harden của ta yêu cầu.

## 2. Bulk: chỉ giữ đúng một bản mới nhất cho mỗi grain

- `psd_alldata_csv.zip` (2 090 920 dòng, Last-Modified 10-07-2026): **0 grain nào có >1 dòng** — file chỉ chứa bản sửa đổi cuối cùng, các vintage cũ bị ghi đè mỗi kỳ phát hành.
- Cột `Calendar_Year`+`Month` được xác minh thực nghiệm là **timestamp của lần sửa cuối** (không phải MY start): CY−MY trải từ 0 đến 46 năm; các dòng mới nhất mang đúng tháng phát hành hiện hành (07/2026); khối dòng cũ dồn về 2006 — thời điểm PSD Online migrate dữ liệu.
- Đây là thông tin release **thật** duy nhất trong bulk, nhưng chỉ 1 điểm/grain — không phải chuỗi as-of.

## 3. Coverage vintage-stamp theo commodity × country × attribute

| Series | Stamped | Unstamped (Month=0) | First stamp | Last stamp |
|---|---|---|---|---|
| CORN @US (cả 3 role) | 67/67 | 0 | 2006-07 | 2026-07 |
| WHEAT @US (cả 3 role) | 67/67 | 0 | 2006-07 | 2026-07 |
| SOYBEAN @US (cả 3 role) | 63/63 | 0 | 2006-06 | 2026-07 |
| RICE @TH (cả 3 role) | 67/67 | 0 | 2006-07 | 2026-07 |
| SUGAR imports @CH | 28/67 | 39 | 2006-05 | 2026-05 |
| SUGAR inventory @IN | 26/67 | 41 | 2008-05 | 2026-05 |
| ROBUSTA @VM (3 metric) | 23/66 | 43 | 2010-06 | 2025-12 |

- SUGAR/ROBUSTA có nhiều dòng `Month=0` (không có tháng) → stamp không tin được cho phần lớn lịch sử của chúng.
- **SUGAR bị loại khỏi mọi tính toán triad** theo quyết định đã khóa: CN imports + IN inventory là hai thị trường khác nhau, không phải một triad kinh tế thống nhất.

## 4. Fold visibility tính lại (folds=5, min_train=252, horizon=90; giá Yahoo thật 2000→2026)

| Commodity | Kịch bản A: `release_date` = ngày ingest | Kịch bản B: `release_date` = stamp lần-sửa-cuối |
|---|---|---|
| CORN | **0/5** | 4/5 (fold 2007→2026 thấy ≥26–64 bản ghi/role; fold 2001 thấy 0) |
| WHEAT | **0/5** | 4/5 |
| SOYBEAN | **0/5** | 4/5 |
| RICE | **0/5** | 4/5 |

- Kịch bản B **leak-free** (giá trị stamped 2006 đúng là thứ đã công bố lúc đó) nhưng **không phải as-of vintage thật**: record bị sửa gần đây trở nên "vô hình" ở cut cũ dù khi đó đã có giá trị sơ bộ; giá trị stamped-2006 là bản-đã-sửa-đến-2006, không phải chuỗi mà thị trường thấy từng tháng trước đó. Dùng B làm nền backtest mechanistic sẽ trộn một phần thông tin sửa đổi tích lũy → **không đạt chuẩn PIT của dự án**, chỉ có giá trị tham khảo về mật độ dữ liệu.
- Kết luận giữ nguyên: mechanistic **không được đánh giá trên lịch sử** cho tới khi có vintage thật.

## 5. Revision identity

- Vì bulk chỉ giữ 1 dòng/grain, **chuỗi revision quá khứ không thể tái dựng** — không thể gán `revision=0,1,2,…` cho các kỳ phát hành đã qua mà không bịa dữ liệu.
- Forward-only thì nhất quán: mỗi kỳ ingest tương lai mang `release_date` mới (grain writer `…, release_date, revision` duy nhất), vintage thật **tích lũy dần từ nay về sau** — sau ~252 phiên giao dịch hậu-ingest thì fold đầu tiên bắt đầu thấy driver một cách hợp lệ.

## 6. Nguồn thay thế đã xét (đều không đạt trong phạm vi pack)

- **Wayback Machine** snapshot của bulk URL: CDX API trả 429 (rate-limited) cả 3 lần thử trong audit — độ phủ snapshot **không xác định được**; kể cả có, đó là độ phủ cơ hội (không phải mỗi kỳ phát hành), chỉ đáng làm pack riêng nếu được duyệt.
- **WASDE archive** (Cornell ESMIS, từ 1973) giữ vintage thật hàng tháng nhưng là nguồn khác (OCE, US + world aggregate), schema/attribute khác PSD country-grain — nằm ngoài phạm vi pack này.

## 7. Latent risk ghi nhận (không sửa trong pack này)

- `etl/sources/supply_demand/usda_psd.py` (connector API cũ, không được `build_connectors` nối vào supply_demand): vẫn chưa có lọc country (response API không mang country), unit hardcode "1000 bags", `source_record_id` không có country. Nếu ai kích hoạt lại sẽ tái tạo đúng lỗi country-collapse đã vá ở bulk connector. **Giữ nguyên, chưa kích hoạt, chưa sửa** — cần pack riêng nếu muốn dùng.

## Kết luận

`FEASIBILITY_FAIL` → chốt **forward-only**: không có đường dựng vintage lịch sử đáng tin cậy từ PSD API/bulk trong môi trường hiện tại (không API key, không endpoint vintage được tài liệu hóa, bulk đơn-vintage, archive không xác minh được). Mechanistic trên lịch sử **vẫn khóa**; con đường hợp lệ duy nhất là tích lũy vintage thật từ các kỳ ingest tương lai. Chưa cấp quyền ingest/push/MV/cutover từ pack này.
