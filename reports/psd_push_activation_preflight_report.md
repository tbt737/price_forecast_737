# PSD_PUSH_ACTIVATION_PREFLIGHT — báo cáo (chưa push / dispatch / ingest / write)

- Base: `357e811` (PSD_CONNECTOR_PATH_UNIFICATION local PASS). PIT vẫn forward-only / 0-of-5 folds (blocker riêng).
- Câu hỏi của pack: sau khi push `origin/master..HEAD`, workflow ingest hiện hữu có tự động collect/write các series PSD liquid mới không?

## VERDICT: **PUSH_SAFE** (sau khi thêm gate mặc định OFF trong pack này; 1 điều kiện xác minh nêu ở mục 7)

## 1. Nội dung sẽ push (`origin/master..HEAD`)

9 commit, 30 file, +4 882 / −325 dòng:

| Commit | Nội dung |
|---|---|
| `d289892` | CommodityPricePredictor + mechanistic_fourier_supply (ml) |
| `6a34e0d`→`ff46307` | SUPPLY_DRIVER_AVAILABILITY_AUDIT (ml, read-only) + fixes |
| `0152103` | PSD liquid config-only (sources.yaml + catalog + validate) |
| `2f98ef5` | Country-grain hardening (config/connector/tests) |
| `5c78d4d` | PIT vintage feasibility audit → forward-only |
| `357e811` | Connector path unification (API cũ disabled fail-closed) |
| *(pack này)* | Gate ingest PSD mặc định OFF + contract tests |

Nhóm file: `configs/ingestion/*`, `etl/{ingest,ingestion,sources/supply_demand}`, `ml/*` (predictor/backtests — không đụng workflow), `scripts/*` (audit read-only), `tests/*`, `reports/*`. **Không commit nào sửa `.github/workflows/`** trước pack này.

## 2. Truy vết mọi đường ingest scheduled/manual tới `supply_demand`

| Đường | Trạng thái với supply_demand |
|---|---|
| `ingest.yml` (cron 22:00 UTC + `workflow_dispatch`) | Mọi step gọi `etl.ingest` đều có `--sources` **tường minh**: `prices`, `vn_prices`, `vn_history`, `vn_stocks` (flag-gated), `macro`, `weather`, `events`. **Không có** `supply_demand`, **không có** `all` |
| `accuracy-writer.yml` / `accuracy-evaluator.yml` | Chỉ ghi/đánh giá `fact_forecast_log`; không chạy `etl.ingest` |
| `vn-freshness-monitor.yml` | Read-only DB |
| `ci.yml` | pytest/lint — tests PSD dùng fixture, không network, không DB write |
| `refresh_ml_features.py --write` (trong ingest.yml) | Refresh MV từ facts hiện hữu — không có fact PSD nào được ghi nên không mang liquid vào MV |
| CLI thủ công `python -m etl.ingest` / `make etl-run` | `--sources` default = **`all`**, và `all` bao gồm `supply_demand` → **activation path có thật** (đặc biệt `--backfill` ghi thẳng ON CONFLICT DO NOTHING) |

## 3. Kết luận auto-activation

- **Scheduled/dispatch sau push: KHÔNG** — không workflow nào chạm `supply_demand` hay `all`.
- **Nhưng tồn tại activation path thủ công/tương lai**: (a) ai đó chạy `python -m etl.ingest --backfill` (default `all`) sẽ collect + write toàn bộ series liquid; (b) một edit workflow tương lai thêm `--sources supply_demand` hoặc `all` sẽ kích hoạt âm thầm. → Theo yêu cầu pack, đã thêm gate.

## 4. Gate mặc định OFF (thay đổi duy nhất của pack này)

`etl/ingest.py` — `build_connectors`:

- Connector PSD chỉ được tạo khi env `ENABLE_PSD_SUPPLY_DEMAND_INGEST == "true"` (CI: repository variable cùng tên).
- `--sources supply_demand` tường minh mà flag OFF → **raise loudly** (không im lặng trả rỗng).
- Bucket `all` mà flag OFF → bỏ qua PSD (đường quét vô tình bị chặn); các source khác không đổi.
- ROBUSTA được **bảo toàn**: khi flag ON, connector mang đủ series cấu hình gồm ROBUSTA + 5 liquid (test khẳng định); hành vi hiện hữu khi flag OFF không đổi vì trước nay không workflow nào ingest supply_demand.

Tests mới (3): gate OFF mặc định (`all` không chứa PSD; explicit raise; giá trị `"1"` không bật), gate ON bảo toàn ROBUSTA + liquids, và **workflow contract**: mọi lệnh `etl.ingest` trong `ingest.yml` phải có `--sources` tường minh, cấm `--sources all`, và nếu tương lai thêm step `supply_demand` thì bắt buộc điều kiện `vars.ENABLE_PSD_SUPPLY_DEMAND_INGEST == 'true'` (hôm nay phải chưa có step đó).

## 5. Read-back GitHub variables

- **Không đọc được từ môi trường này**: `gh` chưa auth, không có `GH_TOKEN`/`GITHUB_TOKEN`; API variables yêu cầu auth. **Không biến nào bị thay đổi** (đúng ràng buộc pack).
- Biến liên quan đã biết qua repo: `ENABLE_VN_STOCKS_INGEST` (gate VN30, tài liệu ghi OFF — không liên quan PSD). Biến gate mới `ENABLE_PSD_SUPPLY_DEMAND_INGEST` **chưa từng được tạo** → trạng thái unset ⇒ OFF theo thiết kế cả trong CI (`vars.X == 'true'` là false khi unset) lẫn CLI (env unset ⇒ skip/raise).

## 6. Hygiene checks (chạy thật sau mọi sửa đổi)

| Check | Kết quả |
|---|---|
| `git diff --check origin/master..HEAD` (+ worktree) | 0 lỗi whitespace/conflict-marker |
| Secret scan diff committed + staged + worktree (AWS key, private key, gh token, JWT, DB-URL-có-credentials, `*.supabase.co`, api_key/password gán giá trị, `.env` tracked) | **SECRET_SCAN_PASS (0 hit)** |
| compileall | exit 0 |
| ruff toàn repo | sạch |
| mypy `app` + `etl` | 0 lỗi (28 + 34 files) |
| pytest full | **554 passed, 1 skipped** (skip = cần Postgres) |
| workflow YAML check | OK (5 workflows) |

## 7. Verdict & điều kiện

**PUSH_SAFE** — sau push: không workflow nào tự collect/write PSD; đường CLI `all` và mọi edit workflow tương lai đều bị gate mặc định OFF chặn; secret scan sạch; full gates xanh.

Điều kiện xác minh kèm theo (thao tác UI, ngoài khả năng môi trường này): trước/ngay sau push, xác nhận trong Settings → Actions → Variables rằng **không tồn tại** biến `ENABLE_PSD_SUPPLY_DEMAND_INGEST` (hoặc giá trị ≠ `true`). Nếu tồn tại `=true` từ trước (xác suất ~0 vì tên biến vừa được đặt trong pack này), gate coi như đã bật — phải xóa/đặt lại trước push.

Vẫn chưa thực hiện: push, dispatch, ingest, MV/cutover, production write. Kích hoạt ingest PSD thật (bật flag) là pack riêng, và PIT forward-only vẫn là blocker cho mechanistic lịch sử.
