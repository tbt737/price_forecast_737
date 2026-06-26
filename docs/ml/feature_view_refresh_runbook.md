# Feature View Refresh Runbook (Phase 5C)

## Quy trình cập nhật Materialized View
Do lượng dữ liệu lịch sử khá lớn, việc refresh toàn bộ Materialized View có thể tốn thời gian và gây block các truy vấn đọc của ML Model (nếu đang trong quá trình training hoặc backtest).

Giải pháp: Sử dụng `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

### Điều kiện tiên quyết
Đã có `UNIQUE INDEX` trên view `mv_ml_daily_features_wide` theo `(commodity_key, as_of_date)`. (Được cấu hình trong file `db/views/011_indexes_ml_feature_views.sql`).

### Lệnh thực thi hằng ngày
Mỗi ngày sau khi quá trình ETL chạy xong và dữ liệu Fact đã được nạp đầy đủ, hệ thống Scheduler (Airflow / GitHub Actions / Cron) cần chạy:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_ml_daily_features_wide;
```

### Quy trình khi Config YAML thay đổi
Khi một commodity mới được thêm vào hoặc có một metric mới được khai báo trong YAML, số lượng cột của view sẽ thay đổi. Phải thực hiện quy trình sau:
1. Sinh lại mã SQL Wide View: `python db/views/compile_ml_feature_views.py`
2. Xóa view cũ (nếu có thay đổi cột): `DROP MATERIALIZED VIEW mv_ml_daily_features_wide;`
3. Chạy lại file SQL được sinh ra: `psql -f db/views/generated/010_mv_ml_daily_features_wide.sql`
4. Tạo lại index để cho phép refresh song song: `psql -f db/views/011_indexes_ml_feature_views.sql`
