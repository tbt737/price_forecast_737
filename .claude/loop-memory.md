# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-07-22 WEEKLY-MOVERS-1B + ACTIVATION — PUSHED_PENDING_CHANNEL_CONFIG (3f7a56a pushed)
1B shipped: idempotency (bảng ops cô lập `alert_delivery_log`, migration 006 RLS-enabled,
claim-first theo `period_key` ISO-week ICT + config-fp + destination-fp; delivered=never
resend, pending=fail-closed skip + un-stick doc, failed=retry qua compare-and-set race-safe;
Sunday-ICT rolls vào tuần tới; dry-run không đụng bảng) + freshness gate (trading-day aware:
global lag >3 ⇒ refuse; per-asset skew >5 ⇒ loại + hiển thị; unavailable+stale >50% ⇒ refuse)
+ `permissions: contents: read`. Review độc lập bắt MAJOR CAS-race thật (UPDATE re-arm thiếu
`AND status='failed'`) + 2 mutant sống → đã vá + test race/CAS/pending-in-flight. Suite
**606+1skip** (27 test pack). Push `9247157..3f7a56a` (đúng 4 commit đã duyệt, không lẫn
workstream 14-mã). Dispatch dry-run trên Actions: run #1 id 29874353020, SHA 3f7a56a,
SUCCESS 4m03s (compute 3m28s ≈ full 66-mã scan); GREEN + zero channel secrets ⇒ chứng minh
logic đường dry-run (send-no-channel tất yếu exit 1 đỏ). Secrets: chỉ DATABASE_URL —
**chưa có kênh** ⇒ chưa live-send. Freshness gate lập tức chặn CHINESE_GARLIC (stale) khỏi
bản tin — mã từng top GIẢM −11.1% trên dữ liệu cũ.
**Rules distilled:** (1) UPDATE re-arm trạng thái phải compare-and-set (`AND status=cũ` +
rowcount) — pre-check status() không race-safe. (2) Actions log viewer ảo hóa chống
get_page_text; logs API cần admin — thiết kế bằng chứng CI theo exit-code semantics được
test ghim thay vì trông vào đọc log. (3) Bảng public mới sau 004 phải ENABLE RLS trong
migration (script CREATE IF NOT EXISTS portable không làm được).

## 2026-07-22 WEEKLY-MOVERS-1 — WEEKLY_MOVERS_1_PASS (local commit da81691; push + secrets = owner)
Shipped: weekly Monday-09:00-ICT bulletin (cron 0 2 * * 1) ranking every forecastable
asset by expected 30-session move via the production forecaster (read-only): top 5/5 up
(commodities/equities), 3/3 down — `configs/alerts/weekly_movers.yaml` +
`scripts/weekly_movers_alert.py` (dry-run default, --send opt-in) +
`.github/workflows/weekly-movers.yml` (no continue-on-error; manual dispatch = dry-run
mặc định) + 17 offline tests (stubbed forecaster, exit codes, channel isolation,
truncation, workflow contract). Notifier: Telegram + SMTP, env-secrets only, per-channel
isolation, (delivered, failed) record; urllib GIỮ NGUYÊN (HTTPError không nhúng URL/token
— requests thì có, đừng "hiện đại hóa"). Fail-closed: DBAPIError giữa scan abort loudly
(không bao giờ gửi bản tin cụt gắn nhãn sai); >50% mã không dự báo được ⇒ từ chối gửi;
--send không có kênh ⇒ exit 1. Smoke thật trên prod: 66 mã quét, 6 không dự báo được,
bản tin thật in đúng (VIB +16.2% dẫn đầu equity). Suite 579→596 (+1 PG skip); tree bẩn
là workstream 14-mã của owner — pack không đụng, chỉ 4 file mới.
**Rules distilled:** (1) bare `except Exception` quanh vòng lặp DB biến sự cố hạ tầng
thành "unavailable" và gửi báo cáo sai — luôn tách DBAPIError ra propagate. (2) Windows
console cp1252 chết vì emoji — mọi script in tiếng Việt/emoji cần
`sys.stdout.reconfigure(encoding="utf-8")`. (3) Manual workflow_dispatch phải dry-run
mặc định khi hành động là gửi tin thật.

## 2026-07-11 RESTATE-1 + HOTFIX — RESTATE_1_PASS (prod API/web redeployed; VN30 data canary still gated)
Shipped (commit `9f10657`): `etl/restatement.py` + `--reconcile` CLI (dry-run default,
INV-7) + `vn_stocks.reconcile` YAML; single-basis latest-revision reads in
`ml/forecast.load_price_series` + `/commodities/{code}/prices`; restatement rows stamp
`release_date=reconcile day` (PIT); coverage guard = stored-date overlap (not raw row
count — reviewer PoC); backfill goes through provenance `gate()`; accuracy evaluator
LOOKUP_ACTUAL mirrors DISTINCT dates + latest revision; forecast cache fingerprint
includes `max(revision)`; ingest.yml MV refresh step (`scripts/refresh_ml_features.py`,
non-blocking); CI mypy + web typecheck; ProfileDetail `allSettled`; `ForecastOut`; docs
sync (PLAN/README/ARCHITECTURE/DEPLOY/sources.yaml).
Prod hotfix (same commit): Cloud Run `cqp-api-00008-ng4` + `cqp-web-00013-7zj` — fixed
500 on `/commodities` after `db-load` wrote `commodity_group=equity` rows that the old
API StrEnum could not deserialize (`/stats` COUNT stayed healthy). Smoke: health/ready/
stats/commodities/GOLD/VCB_VN + web `/` `/stocks` `/api/commodities` all 200.
Invariants: INV-1/2 (restatement stays offline; connector is network boundary), INV-3
(release_date stamp), INV-4 unchanged at 51/98, INV-7 (no prod write/backfill; flag
`ENABLE_VN_STOCKS_INGEST` still OFF).
Gates at land: pytest **473+1skip** · vitest **39** · ruff 0 · mypy 0 · build ✓.
**Still gated (PLAN §5):** production canary backfill 1–2 tickers → full 30 → re-enable
scheduled reconcile. **Residual CLOSED by round-2 hardening (same day):**
`build_pandas_mv` now revision-aware (per-instrument max revision) + deterministic
collapse (sort before groupby.last — read_sql has no ORDER BY); reconcile window
auto-reaches the stored tail (`min(today−N, max(stored)−3d)`) so a gap > N days (Tết)
can't strand `no_anchor`; `no_anchor` now counts into `ok:false` ⇒ exit 1 (visible
stall); mutation-guard in `_series` pins the ML revision filter; epsilon boundary
(0.4%→fresh / 0.6%→restate), rev-1 release_date=reconcile-day, and gap-recovery tests
added (suite 476+1skip).
**Rules distilled:** (1) Never `db-load` a new enum/group value into live dims before the
serving API revision knows that value — COUNT endpoints will lie green while list/detail
500. (2) Coverage for restatement reloads must be intersection-of-dates, never
len(payload)/len(stored). (3) Hotfix deploy order: API smoke (incl. one new-group row)
before web. (4) Adversarial reviewers should mutation-test the pack's central invariant —
two "green" tests here were provably not pinning it (dict(zip) masked duplicates;
append-at-rev never exercised post-restatement). (5) A fail-closed skip that repeats
daily is a silent stall — every self-repeating skip status must turn the run red.

## 2026-07-11 VN30-STOCKS-1 — VN30_STOCKS_1_PASS (prod phase gated, see PLAN §5)
Shipped: 30 VN30 equity profiles (`configs/commodities/<ticker>_vn.yaml`, group `equity`,
basket effective 2026-02-02) + `vn_stocks` connector (`etl/sources/market/vn_stocks.py`,
TradingView-arrays parser, ×1000 VND scale from config, explicit-only like vn_history,
fail-soft incl. url_template.format inside try) + `VnStockSpec` config block + ENTRADE seed
+ ingest.yml 7-day top-up step (inert until prod seed) + web `/stocks` page (group-scoped
`CommodityExplorer` via new `filterByGroup`; home excludes equities; equity chip 📈).
Invariants: INV-1/2 (guards re-registered, NETWORK_EXEMPT ×2), INV-4 bumped to REAL counts
51 profiles/98 instruments (also PLAN §2), INV-6 verified live (401 without key), INV-7
untouched (no prod writes; smoke = isolated SQLite + injected/real fetch, forecast proven
end-to-end: FPT_VN 476 rows → naive fallback, MAPE 3.8%).
Gates: pytest **456+1skip** · vitest **39** · ruff 0 · mypy 0 (28+32) · build ✓ (new baseline).
Adversarial review (2 independent + convergence): fixed url_template crash + NaN/Infinity
filter + 4 guard tests; **open design debt — adjusted-price restatement vs append-only
ingest** (chart API restates history at each corporate action; heal = revision-aware reload
using the existing `revision` grain column) — documented in sources.yaml, follow-up pack
chipped; land it before/with the first prod backfill.
**Rules distilled:** (1) never run `npm run build` while the dev server serves the same
`.next` — it corrupts the dev cache ("Cannot find module './NNN.js'"); restart dev after.
(2) A restating (adjusted) price source is a NEW data class on this platform — check
append-only assumptions before onboarding the next one. (3) Port 3000 may be occupied by
a foreign process — smoke on 3100.

## 2026-07-07 PLAN-SOT — PLAN_SOURCE_OF_TRUTH_BOOTSTRAP_PASS
Docs-only pack: created root `PLAN.md` (11 sections; authoritative planning entry point;
ACC-REVIEW recorded WAITING on first matured `fact_forecast_log` rows). Adversarial review
(2 independent reviewers) caught a wrong golden number: repo has **20** commodity profiles
(test-pinned), not 16 — fixed in PLAN.md + this profile's baseline/INV-4 + entry below.
**Rules distilled:** (1) seed golden numbers from the pinning TEST, never from README/docs —
`README.md` (16) and `ARCHITECTURE.md` header (18, "cloud hosting pending") are stale; PLAN.md
§2 note supersedes them. (2) Branch-protection checks must use full display names
`Python (lint + tests)` / `Web (lint + test + build)`. Gates: structure-check ALL PASS,
`git diff --check` clean, pytest untouched (docs-only).

## 2026-07-07 BOOTSTRAP — LOOP_BOOTSTRAP_PASS
Created `.claude/loop-profile.md` (gates, 7 locked invariants, smoke method, budgets) and this
memory file. Baseline locked at commit 4925b9d: pytest **409 passed + 1 skipped**, web vitest
**34 passed**, ruff clean, mypy clean (28 app + 31 etl files), 20 commodity profiles
(bootstrap entry originally said 16 — corrected by PLAN-SOT review). Verified
facts distilled into the profile: dev toolchain is global Python 3.13 (not `.venv`); local
`.env` points at the live Supabase DB, so smoke is GET-only and every write path stays dry-run.
