# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-08-31 WEB-DEPS-AUDIT-1 — WEB_DEPS_AUDIT_1_PASS (autonomous maintenance run)
`npm audit` on `apps/web` found **7 vulnerabilities (1 low, 6 high)**: brace-expansion
(devDep, DoS), esbuild (dev-server-only arbitrary file read, Windows-only), js-yaml
(quadratic CPU), nanoid (infinite loop), sharp/libvips (4 CVEs), postcss (XSS +
path-traversal via sourceMappingURL), and next itself (Server Actions DoS/SSRF/cache
confusion — 7 distinct advisories, `9.3.4-canary.0 - 16.3.0-preview.10`). Checked before
touching anything: `next` has an official stable **`backport` dist-tag at 15.5.24**
(same 15.x line already inside the existing `^15.5.19` range in package.json — not a
major bump) that the Next.js team cut specifically to backport these security fixes.
Applied: `npm audit fix` (no `--force`) bumped next→15.5.24 and fixed brace-expansion/
js-yaml/nanoid/sharp outright; then manually bumped the exact-pinned `postcss` devDep
8.5.1→8.5.26 (same 8.5.x patch line, matching this file's exact-pin convention for
autoprefixer/eslint/prettier/tailwindcss/typescript) + `npm install` to re-resolve the
lockfile — that fixed the **top-level** postcss instance. Net: 7→3 vulnerabilities;
remaining are (a) esbuild 0.27.7 low/dev-only via vite, Windows-only impact, irrelevant
to this Linux/Cloud-Run prod target, and (b) postcss@8.4.31 *bundled inside next's own
node_modules* (next vendors its own copy) — fixing that one requires the Next.js 16.x
major (`next@16.3.3`, `npm audit fix --force` territory), a breaking change out of scope
for an unattended run; flagged, not attempted.
Gates: `npm run typecheck` clean · `npm test` 39/39 (unchanged) · `npm run lint` 0
warnings/errors · `npm run build` succeeds (Next.js 15.5.24, 6 routes, same route shape
as before). Only `apps/web/package.json` (1 line) + `apps/web/package-lock.json`
changed; Python side untouched.
**Rules distilled:** (1) when `npm audit`'s in-range fix looks like it wants to bump a
framework across what looks like a major-version advisory range, check
`npm view <pkg> dist-tags --json` first — a `backport` tag can mean the vendor already
shipped the CVE fix into the existing stable minor line, avoiding a false choice between
"stay vulnerable" and "force a breaking major". (2) An exact-pinned (no caret) transitive
dep that `npm audit fix` skips (because the exact pin blocks it) may still be safely
bumpable by hand within the same minor line — check `npm ls <pkg>` for who else in the
tree already resolved to a newer compatible version before assuming a major jump is
required. (3) A framework that vendors its own nested copy of a dependency (here: next's
private `postcss@8.4.31`) cannot be patched independently of the framework's own major
version — that residual is expected, not a sign the top-level fix failed.

## 2026-08-31 TEST-TIMEBOMB-1 — TEST_TIMEBOMB_1_PASS (autonomous maintenance run)
Full gate run (fresh venv, python3.13 + requirements-dev.txt) found `pytest -q` at
**587 passed, 1 failed** — `tests/quality/test_weekly_movers.py::test_main_exit_codes`.
Root cause: `_forecast_stub`'s fixture hardcoded `last_date="2026-07-21"`; `main()`'s
freshness gate compares that against real wall-clock `datetime.now(UTC)` (no `today=`
override exists in `main()`), so once real time drifted > `max_lag_trading_days` (3
trading days) past the fixture, the "dry-run with data ⇒ 0" assertion started getting
exit 1 instead — a classic hardcoded-fixture-date time bomb, not a product regression.
Fix (`tests/quality/test_weekly_movers.py` only): `_forecast_stub` gained an optional
`last_date` param and now defaults to `date.today() - timedelta(days=1)` instead of a
frozen string, so the "fresh" fixture stays fresh regardless of when the suite runs;
callers that need a deliberately stale date (`test_main_refuses_stale_global_data`)
still pass one explicitly. No production code touched. Swept the rest of the suite for
the same pattern (`grep` for hardcoded `2026-0*` dates near `date.today()`/
`datetime.now()` call sites) — every other hardcoded date in the test suite is compared
against another fixture date, not real wall-clock, so no further time bombs found.
Gates after fix: compileall ✓ · ruff 0 · mypy 0 (28 app + 34 etl) · **pytest 588 passed
+ 1 skipped** (new baseline, PG skip unchanged) · `ci_check_workflows.py` OK (6
workflows). `apps/web` untouched — web gates not run (per loop-profile "only when
apps/web touched").
**Rules distilled:** (1) any test stub whose freshness/staleness assertion runs through
code that calls real `date.today()`/`datetime.now()` with no injectable `today=` must
derive its fixture date from `date.today()` too — a literal date string next to a
real-time comparison is a guaranteed future failure, not a hypothetical one. (2) When
"tests pass" is the baseline claim, always run the actual suite locally before trusting
CLAUDE.md/PLAN.md snapshot text — the last recorded baseline (473+1skip, 2026-07-11) was
long stale (current tree: 588+1skip) simply from normal pack accretion, unrelated to
this bug.

## 2026-07-22 WEEKLY-MOVERS-1D — PUSHED_PENDING_TELEGRAM_SECRETS (4f25ab9 pushed; 007 áp prod)
Least-privilege activation: role `weekly_alert_runner` (LOGIN-only, NOBYPASSRLS, connlimit 3)
+ migration 007 (áp prod ×2 idempotent): read-allowlist đúng call-graph (dim_commodity,
dim_market_instrument, fact_price_daily qua RLS policy + mv_wide grant); delivery log CHỈ
qua 3 SECURITY DEFINER functions (search_path pinned, PUBLIC revoked, CAS server-side,
delivered immutable, pending không re-arm, PK bất khả xâm phạm). DeliveryLog dual-path
(PG=functions / SQLite=SQL test). Workflow đổi secret `WEEKLY_ALERT_DATABASE_URL`
(contract test pin owner-secret vắng mặt). Auditor độc lập KẾT NỐI BẰNG RUNNER: 14/14 PASS
(anon/authenticated denied; DDL/DELETE denied; race 1-winner; rollback sạch; hijack fail).
Credential runner: file `d:\Downloads\cqp-prod-snapshots\WEEKLY_ALERT_DATABASE_URL.txt`
— owner tự dán vào GitHub secret (Claude bị cấm nhập secret vào form). Chờ owner:
WEEKLY_ALERT_DATABASE_URL + TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID → rồi Pack F/G
(dry-run Actions bằng role mới, live smoke 1 lần + rerun dedupe).
**Rules distilled:** (1) psycopg3 parse `%I` trong DO-block như placeholder — migration
dùng quote_ident||concat, không dùng format('%I'); apply qua raw cursor không params.
(2) 004 deny-by-default nghĩa là GRANT SELECT chưa đủ cho role thường — cần RLS policy
FOR SELECT đích danh. (3) Bảng do table-swap tạo lại sẽ mất grant — kiểm tra vòng đời
relation trước khi cấp quyền (ở đây builder mới hard-refuse đụng tên prod nên grant bền).

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
