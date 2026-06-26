# Materialized View Compiler (Phase 5B)

## Vấn đề cần giải quyết
Machine Learning models cần dữ liệu ở định dạng Wide Panel (mỗi feature là một cột). Tuy nhiên, số lượng metrics có thể lên tới hàng trăm, thay đổi liên tục khi cấu hình YAML của các commodity được mở rộng.
Nếu viết thủ công lệnh `CREATE MATERIALIZED VIEW`, chúng ta sẽ gặp khó khăn trong việc duy trì và có nguy cơ lỗi cao.

## Giải pháp: Deterministic YAML Compiler
Script `db/views/compile_ml_feature_views.py` đóng vai trò như một trình biên dịch (compiler):
1. Đọc toàn bộ các file `*.yaml` trong `configs/commodities/`.
2. Extract danh sách các `metric_code` từ các khối drivers (physical, macro, logistics, event_risk).
3. Validate chống SQL Injection.
4. Sinh ra file SQL `db/views/generated/010_mv_ml_daily_features_wide.sql`.

View Wide được sinh ra bằng cách extract dữ liệu từ lớp `v_ml_daily_features_jsonb`:
```sql
(jsonb_path_query_first(features_jsonb, '$[*] ? (@.metric_code == "rainfall_mm").metric_value_numeric'))::numeric AS rainfall_mm
```

**Deterministic grain:** `jsonb_path_query_first` is safe because `v_ml_daily_feature_scalar`
enforces at most one event per `(as_of_date, commodity_key, metric_code)` before `jsonb_agg`.
When the same metric exists across regions or instruments, the scalar view picks a single row
using explicit `DISTINCT ON` ordering (global NULL keys first, then freshest observation).

## Lợi ích
- **Không Hardcode**: Code SQL không biết trước về bất kỳ commodity nào.
- **Dễ Audit**: File SQL sinh ra (`010_mv_ml_daily_features_wide.sql`) được commit vào source control để review và audit, thay vì execute ngầm.
- **An toàn**: Lớp compiler này lấy input từ Canonical Long View, nên nghiễm nhiên được kế thừa tính chất Point-in-Time correctness, không thể bị Look-ahead bias.
