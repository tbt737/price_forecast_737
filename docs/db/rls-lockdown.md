# RLS lockdown — khóa Supabase Data API (SEC-1A / SEC-1B)

## Vấn đề (P1 từ audit)
Supabase mặc định expose schema `public` qua Data API (PostgREST) và **grant quyền cho
role `anon`/`authenticated`**. 3 migration đầu không bật RLS → ai cầm **anon key công
khai** có thể đọc VÀ GHI `fact_price_daily` (đầu độc mọi dự báo đang phục vụ).

## Vì sao khóa được an toàn (đã verify bằng code + panel phản biện 3-lens)
- Toàn bộ app (API / ETL / CI) kết nối **chỉ qua `DATABASE_URL`** với role **chủ sở hữu
  bảng** (chính role đã apply migration 001–003 và tạo mọi object).
- Repo **không có chỗ nào** dùng supabase-js / supabase-py / anon key / PostgREST
  (tripwire: `test_repo_still_has_no_supabase_data_api_usage` FAIL nếu ai thêm vào sau).
- RLS thường (không `FORCE`) **không áp lên table owner** → backend/ETL không đổi hành vi.

## Migration `db/migrations/004_rls_lockdown.sql` làm gì
1. `ENABLE ROW LEVEL SECURITY` trên mọi bảng (`r` + partitioned `p`) trong `public`
   **thuộc sở hữu role đang chạy** (bảng của role khác → skip + NOTICE, không abort).
   **Không policy nào** ⇒ deny-by-default cho role không-phải-owner. **Không FORCE**.
2. `REVOKE ALL` **tables + sequences + functions** khỏi `anon`/`authenticated`
   (functions = chặn cả bề mặt PostgREST `/rpc/` tương lai) + `ALTER DEFAULT PRIVILEGES`
   tương ứng để object tạo sau này không tự mở lại quyền. Guard `pg_roles` ⇒ chạy được
   trên Postgres thường (docker-compose, nơi 2 role đó không tồn tại). `service_role`
   giữ nguyên. **File này chỉ REVOKE — không bao giờ GRANT** (test cấm token GRANT).
3. `REVOKE ... FROM PUBLIC` (tables/sequences/functions + default privileges). **Bắt buộc:**
   `anon`/`authenticated` KẾ THỪA quyền từ `PUBLIC`, nên revoke ở bước 2 chưa đủ — Postgres
   mặc định `GRANT EXECUTE` mọi function mới cho `PUBLIC` (điểm hở RPC lớn nhất tương lai).
   Owner (role DATABASE_URL) giữ nguyên toàn quyền qua ownership — revoke PUBLIC không đụng.

File gồm **đúng 3 DO-block** (anon-guard, authenticated-guard, PUBLIC).

Idempotent, additive, **không đổi 1 dòng dữ liệu nào**.

## ⚠️ Preconditions khi apply (SEC-1B — phase kiểm soát riêng, CHƯA chạy)
1. **Apply bằng đúng role DATABASE_URL / table-owner** (trên Supabase = `postgres`).
   `ALTER DEFAULT PRIVILEGES` chỉ sửa default ACL của role thực thi — chạy bằng role
   admin khác sẽ **âm thầm vô hiệu** phần bảo vệ object tương lai.
2. File là **đúng 3 statement** (3 `DO $$ … END $$;`). **KHÔNG split theo `;`** (bài học
   ACC-1B — dấu `;` nằm BÊN TRONG block). Apply đúng:
   ```python
   blocks = re.findall(r"DO \$\$.*?END \$\$;", raw_sql, flags=re.S)
   with engine.begin() as conn:
       for b in blocks:
           conn.exec_driver_sql(b)
   ```
   (hoặc `psql -f 004_rls_lockdown.sql` — psql hiểu dollar-quote.)
3. Mỗi `ENABLE RLS` lấy **ACCESS EXCLUSIVE lock ngắn** trên từng bảng → chọn lúc traffic
   thấp (sau giờ chạy ingest 22:00 UTC là ổn).

### Verify sau apply (read-only — cả 3 query phải đạt)
```sql
-- 1) RLS bật trên các bảng base? (relrowsecurity = t)
SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY 1;

-- 2) anon/authenticated hết sạch quyền trên MỌI relation — kể cả MATVIEW
--    (không dùng information_schema.role_table_grants: nó BỎ SÓT matview)
SELECT c.relname, a.grantee::regrole::text AS role, a.privilege_type
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE n.nspname='public' AND c.relkind IN ('r','v','m','f','p')
  AND a.grantee::regrole::text IN ('anon','authenticated');   -- kỳ vọng: 0 dòng

-- 3) default ACL tương lai không còn anon/authenticated
SELECT pg_get_userbyid(d.defaclrole) AS grantor, d.defaclobjtype, d.defaclacl::text
FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace
WHERE n.nspname='public' AND d.defaclacl::text ~ '(anon|authenticated)';  -- kỳ vọng: 0 dòng
```
**Ngoại lệ đã biết ở query 1:** `mv_ml_daily_features_wide` — nếu đã được
`ml/build_pandas_mv.py` rebuild thành **bảng thường** thì bảng mới tạo sau apply sẽ có
`relrowsecurity = f`. Không phải lỗ hổng (anon bị chặn bởi revoke + default privileges —
query 2/3 mới là bằng chứng đóng lỗ), nhưng bảng đó chỉ còn 1 lớp bảo vệ thay vì 2.
Tùy chọn tương lai (ngoài scope SEC): builder tự `ENABLE RLS` trên staging table.

**Bằng chứng đóng đúng attack-path (tùy chọn, làm tay):** từ máy ngoài, gọi
`https://<project>.supabase.co/rest/v1/fact_price_daily?select=*&limit=1` với header
`apikey: <anon key>` → kỳ vọng **permission denied / 401**, không phải dữ liệu.

Rồi smoke app: `/stats`, `/commodities/gold_vn/prices` trả dữ liệu như cũ
(DATABASE_URL = owner, không bị ảnh hưởng).

### Khuyến nghị kèm theo (làm tay trên Supabase dashboard, không thuộc migration)
- Settings → API: cân nhắc **tắt hẳn Data API cho schema `public`** (belt-and-suspenders).
- Xác nhận password DB (từng lộ trong chat, đã rotate 2026-06-25) đúng là đã rotate.

## Rollback (chỉ khi được duyệt — không chạy tự động)
```sql
ALTER TABLE public.<table> DISABLE ROW LEVEL SECURITY;          -- per-table
GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;            -- CHỈ khi thật sự cần Data API đọc
```

## Nếu tương lai cần Data API thật
Đừng disable RLS — viết `CREATE POLICY ... FOR SELECT TO anon USING (true)` **cho đúng
bảng cần đọc công khai** (trong migration MỚI, không sửa 004), giữ deny-by-default cho
phần còn lại. Tripwire test sẽ nhắc việc này.
