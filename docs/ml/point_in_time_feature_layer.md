# Point-in-Time Feature Layer (Phase 5A)

## Tầm nhìn kiến trúc
Lớp Point-in-Time (PIT) Feature Layer là trái tim của hệ thống Machine Learning đa hàng hóa. Mục đích duy nhất của nó là ngăn chặn triệt để rủi ro **Look-ahead Bias** – kẻ thù số 1 của mọi hệ thống backtest giao dịch.

Để ML model có thể học được "thực tế tại thời điểm T", chúng ta phải tái tạo chính xác bức tranh thông tin mà thị trường biết được vào ngày hôm đó.

## Nguyên tắc 3 Ngày (The 3 Dates)

Hệ thống phân tách rõ 3 khái niệm thời gian:
1. `observation_date` / `period_end`: Ngày mà dữ liệu thực sự đại diện (Ví dụ: lượng mưa ngày 10/1).
2. `release_date`: Ngày mà dữ liệu được công bố và có thể dùng được (Ví dụ: số liệu lượng mưa ngày 10/1 được NASA công bố vào ngày 12/1).
3. `as_of_date`: Ngày giả định mà model đang đứng để nhìn về quá khứ (Lưới thời gian).

## Canonical Long View (`v_ml_daily_feature_events_long`)

Thay vì pivot ngay thành bảng rộng (Wide Panel), dữ liệu được hợp nhất thành một bảng dọc (Long Format) chứa các sự kiện đặc trưng (feature events).

**Lợi ích của Long View:**
- **Dễ audit**: Cung cấp lineage (nguồn gốc) chi tiết tới từng `source_table`, `source_fact_id`.
- **Dễ test**: Các test integration có thể dễ dàng query để xác minh tính đúng đắn của logic PIT.
- **Không hardcode**: Số lượng metric có thể mở rộng tùy ý theo YAML config mà không cần sửa cấu trúc bảng hay tạo hàm Dynamic SQL phức tạp.

**Quy tắc Point-In-Time:**
Với mọi dữ liệu được lấy vào, view luôn áp dụng:
```sql
fact.observation_date <= grid.as_of_date
AND fact.release_date <= grid.as_of_date
```
Giá trị trả về là phiên bản mới nhất (`ORDER BY observation_date DESC, release_date DESC, revision DESC`) thỏa mãn điều kiện trên.

## Scalar Collapse View (`v_ml_daily_feature_scalar`)

Wide-panel ML models require exactly one scalar per `(as_of_date, commodity_key, metric_code)`.
The long view preserves region and instrument grain, so the same `metric_code` can appear
multiple times (e.g. weather across regions, prices across instruments).

`v_ml_daily_feature_scalar` collapses duplicates with deterministic `DISTINCT ON` tie-breaking:

1. `region_key NULLS FIRST`, then lowest `region_key` (prefer global metrics)
2. `instrument_key NULLS FIRST`, then lowest `instrument_key`
3. `observation_date DESC`, `release_date DESC`, `source_fact_id DESC`

This removes nondeterministic "first row wins" behaviour in downstream wide extraction.

## Aggregation View (`v_ml_daily_features_jsonb`)

View `v_ml_daily_features_jsonb` aggregates scalar events (not raw long events) into a JSONB
array per `(as_of_date, commodity_key)`. Each `metric_code` appears at most once, so the
Phase 5B compiler can safely use `jsonb_path_query_first` for wide-column extraction.
