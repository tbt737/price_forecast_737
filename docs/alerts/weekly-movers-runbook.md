# Weekly movers bulletin — runbook vận hành

> Workflow: `.github/workflows/weekly-movers.yml` (cron `0 2 * * 1` = **Thứ Hai 09:00
> giờ Việt Nam**; manual dispatch mặc định DRY-RUN). Script:
> `scripts/weekly_movers_alert.py` (dry-run mặc định; `--send` mới gửi thật).
> Config: `configs/alerts/weekly_movers.yaml`. Idempotency: bảng
> `public.alert_delivery_log` (migration `db/migrations/006`).

## 1. Quy tắc kỳ bản tin (period_key) — GHI CHÚ NGHIỆP VỤ

`period_key = weekly-movers:<ISO-year>-W<ISO-week>:<config-fp>` tính theo ngày **ICT**,
với MỘT quy tắc nghiệp vụ không phải ISO thuần: **Chủ nhật (ICT) được cuộn sang thứ Hai
kế tiếp** — bản tin là sản phẩm neo vào sáng Thứ Hai, nên một lần gửi tay tối Chủ nhật
và lần cron sáng Thứ Hai thuộc CÙNG một kỳ (không gửi trùng). Biên năm đi theo ISO của
ngày-sau-cuộn (có test pin: 2026-W53, 2027-W01, 2029-W01 —
`tests/quality/test_weekly_movers.py::test_period_key_sunday_rollover_year_boundaries`).

## 2. Trạng thái giao nhận & un-stick `pending`

Mỗi (kỳ, kênh, destination-fingerprint) có một record: `pending` → `delivered`/`failed`.

- `delivered`: không bao giờ gửi lại kỳ đó.
- `failed`: lần chạy sau tự retry riêng kênh đó (compare-and-set, an toàn race).
- `pending` tồn đọng = tiến trình chết giữa chừng — **KHÔNG RÕ tin đã tới hay chưa**.
  Script luôn fail-closed (bỏ qua, không đoán).

**Quy trình un-stick (BẮT BUỘC kiểm kênh thật trước — cấm re-arm mù):**
1. Mở kênh thật (chat Telegram / hộp thư người nhận) và xác nhận bản tin của ĐÚNG kỳ đó
   đã đến hay chưa (đối chiếu tiêu đề + thời gian trong tin).
2. Đã đến → `UPDATE alert_delivery_log SET status='delivered', updated_at=now() WHERE
   period_key=... AND channel=... AND destination_fp=...;`
3. Xác nhận CHƯA đến → đổi thành `failed` (re-arm) bằng câu UPDATE tương tự; lần chạy
   sau sẽ gửi lại.
4. Không bao giờ đổi `pending→failed` chỉ vì "chắc là chưa gửi".

## 3. Freshness gate — hành vi định trước

- Dữ liệu mới nhất trễ > `freshness.max_lag_trading_days` (mặc định 3 **ngày giao
  dịch**, cuối tuần không tính) ⇒ run ĐỎ, không gửi (ingest hỏng).
- Mã lệch as-of > `max_asset_skew_trading_days` (5) so với mã mới nhất ⇒ loại khỏi
  bảng xếp hạng, hiển thị số lượng trong bản tin.
- **Sau kỳ nghỉ dài (Tết):** thị trường VN đóng >5 phiên trong khi hàng hóa quốc tế vẫn
  chạy → equity bị loại hàng loạt → vượt ngưỡng 50% ⇒ bản tin Thứ Hai đầu sau Tết ĐỎ
  CÓ CHỦ ĐÍCH. Không cần xử lý; kỳ kế tiếp tự bình thường.

## 4. Secrets kênh (tạo trên GitHub → Settings → Secrets → Actions)

- Telegram (kích hoạt trước): `TELEGRAM_BOT_TOKEN` (@BotFather → /newbot),
  `TELEGRAM_CHAT_ID` (nhắn bot 1 tin rồi lấy `chat.id` từ `getUpdates`). Bot PHẢI được
  người dùng nhắn trước thì mới gửi chủ động được. Destination thử nghiệm = chat riêng.
- Email: `ALERT_SMTP_HOST/PORT/USER/PASSWORD`, `ALERT_EMAIL_FROM/TO` (Gmail dùng App
  Password). **STARTTLS-only** — dùng port 587; KHÔNG dùng port 465 (implicit TLS,
  không hỗ trợ). `ALERT_EMAIL_TO` có thể là danh sách phẩy, nhưng fingerprint tính
  trên nguyên chuỗi — đổi danh sách ⇒ kỳ đó được coi là destination mới (gửi lại).
- Thiếu kênh hoàn chỉnh ⇒ run scheduled ĐỎ có chủ đích (fail-closed, không im lặng).

## 5. Live smoke lần đầu (sau khi 006 đã áp lên prod — xem §6)

1. Actions → "Weekly movers alert" → Run workflow → **bỏ tick** `dry_run`.
2. Xác nhận tin đến chat thử nghiệm; đối chiếu số mã quét/loại trong tin.
3. Read-back record: `SELECT * FROM alert_delivery_log ORDER BY created_at DESC LIMIT 5;`
   → kỳ hiện tại, kênh telegram, `delivered`.
4. **Rerun cùng kỳ** (Run workflow, bỏ tick dry_run lần nữa) → log phải in
   `dedupe skip (record: delivered)`, KHÔNG có tin thứ hai, exit 0.

## 6. Migration 006 trên production

Áp `db/migrations/006_alert_delivery_log.sql` qua Session-pooler TRƯỚC lần live đầu
(bảng do script tự tạo sẽ KHÔNG có RLS — tránh). Migration idempotent (CREATE IF NOT
EXISTS + ENABLE RLS chạy lại vô hại). Kiểm chứng: bảng đúng schema + PK
`(period_key, channel, destination_fp)`; `relrowsecurity=true`; anon/authenticated
không có grant; không trigger/default nào chứa dữ liệu người nhận (bảng chỉ lưu
fingerprint SHA-256 rút gọn, không bao giờ lưu chat id/email thô).
