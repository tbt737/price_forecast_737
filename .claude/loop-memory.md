# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-09-03 AUDIT-1B — AUDIT_1B_PASS (adversarial verification of AUDIT-1 + sweep of the untouched areas)
26-agent workflow: 3 skeptics per escalated claim (default REFUTED, must produce a failing input)
→ 1 adjudicator each; 5 finders over the areas nobody had read (db/, configs/, apps/web, worker/
infra/docker, freshness); 1 completeness critic. **Verification changed the answers — 3 of 5
escalated claims did not survive as stated.**
**Verdicts:** restatement 90%-coverage truncation **CONFIRMED HIGH** (probe: 18/20 stored dates
⇒ coverage exactly 0.900 ⇒ accepted, revision bumped, 2 dates gone from every read path, exit 0;
one-line fix at `etl/restatement.py:238` + sources.yaml:182 + the value assert in
test_restatement.py:411 — the 3 happy-path tests all republish 100%, so nothing legitimate
regresses). backfill-write-gate **CONFIRMED MEDIUM but recalibrated**: `--backfill`/`--csv-import`
are the repo's DELIBERATE documented write path (`.claude/skills/backfill-price-history/SKILL.md`
teaches it; ingest.yml uses it at 5 sites) — the defect is the CLI help/docstring claiming
"default is dry-run" while `--write` is silently ignored there, i.e. a contract lie, not a data
bug (append-only, idempotent). POST /forecast **PARTIALLY_CONFIRMED LOW, not a live breach**: the
router is mounted only under `ENABLE_ML_FORECAST_API`, which defaults False and is set by NO
deploy surface (probe under prod env: 404, absent from OpenAPI). ml/runner backtest-vs-serve
mismatch **PARTIALLY_CONFIRMED LOW** — both mechanisms real, but unreachable while
`ENABLE_ML_MODELS_API` is off. harvest-lag **PARTIALLY_CONFIRMED MEDIUM, dormant** — real, but
the cause is BOTH the positional `q_future` slice AND positional `_shift_by_months`; a
slice-only fix repairs only the first forecast month (measured).
⚠️ **Correction to the AUDIT-1 entry below:** it recorded "a test pins the ungated POST behaviour,
so this is a design decision". That is WRONG. `test_forecast_api_gate.py:81-85` is
`test_forecast_route_exists_when_flag_on` — it asserts the flag mounts the route and makes no auth
claim. Git history settles it: forecast.py + that test landed 2026-07-01 (303a17c); the internal-key
gate landed 2026-07-03 (88f0c27) and never touched that router. The gate was never extended to the
flag-off experimental route — a latent tripwire that arms the moment anyone flips the flag on an
`--allow-unauthenticated` service, not a deliberate public endpoint.
**Shipped from this pass (all gates green, 599 passed + 1 skip):** (7) weekly bulletin labelled
prices with the commodity `default_currency` while `last_price` comes from whichever instrument has
the most dates — WHEAT is USD by default but every ingested instrument is USc, so a 543 USc/bushel
close went out as "543 USD" (100x); ROBUSTA/CHINESE_GARLIC serve INR mandi prices under a USD
default. Now carries the payload's own currency. (8) `COMEX_HG` was `USc` in the profile vs `USD`
in the registry (HG=F is quoted USD/lb) ⇒ /forecast and /prices rendered the same copper number
100x apart, and the USc figure fed the AI-chat prompt. Profile corrected + a quality test now pins
registry currency == profile instrument currency, with ONE documented waiver (the Indian garlic
proxy stored on the Jinxiang instrument) and a second test that fails when a waiver goes stale.
(9) bare `python -m etl.ingest` committed 11 dim_data_source rows before dispatch (measured 11→0;
`--write` still seeds 11) — the seeding now sits behind the write-mode guard. (10) `validate_record`
had NO numeric validation at all, so the NaN class was only closed per-connector: it now rejects
NaN/±Inf as NON_FINITE_VALUE at the choke point every record passes through.
**Still open, ranked (nothing below was changed):** restatement coverage 1.0 (do it BEFORE
`ENABLE_VN_STOCKS_INGEST=true`) · `/ai/chat` rate limiter keys on the FIRST X-Forwarded-For entry,
which the client controls, so the 15/min cap never fires and the key map degrades to an O(n) scan
per request — needs the owner's trusted-proxy hop count to fix correctly · 8 of 52 commodities are
in no freshness group at all, and no layer between model and reader carries a staleness signal, so
a months-stale produce series is forecast and rendered exactly like a fresh one · `ml/forecast.py:85-92`
takes `MAX(revision)` per (commodity, instrument) with no per-date grouping — the same defect the
sweep rated HIGH in build_pandas_mv.py, on the LIVE serving path · alembic (`0001`,`0002`) and
`db/migrations/001-007.sql` are two independent definitions of one schema, never compared.
**Rules distilled:** (1) An adjudicated verdict is worth more than a finding — 3 of 5 escalations
changed severity or cause under adversarial checking; never escalate an unverified reviewer claim
to the owner. (2) Fix a data-hygiene class at the validation choke point, not in the connector that
happened to expose it. (3) The INV-2 network guard scans COMMENTS — never name an upstream library
in `etl/` prose.

## 2026-09-03 AUDIT-1 — AUDIT_1_PASS (pushed to `claude/sharp-hopper-l75u32`; 4 items ESCALATED)
Autonomous review pack (3 fresh reviewers over etl/ · ml/ · apps/api+scripts+workflows; every
finding re-verified locally before acting, several by running the real code).
**Shipped — 6 fixes, each pinned by a test that fails without it:**
(1) `test_weekly_movers::test_main_exit_codes` was RED on master — a wall-clock time bomb:
the stub hardcoded `last_date="2026-07-21"` while `main()` measures freshness against the real
clock, so it rotted 3 trading days after it was written. Stub is now relative to `date.today()`.
(2) `vn_domestic`: bare `NaN`/`Infinity` survive `json.loads` and do NOT compare `<= 0` — a
garbled PNJ/VNAppMob row reached `fact_price_daily`. Unrecoverable in place: `Decimal('NaN') !=
Decimal('NaN')` ⇒ every replay is a false `conflict` ⇒ whole batch blocked+rolled back forever;
restatement can't heal it either (`stored <= 0` is False for NaN). Now `math.isfinite`-gated,
matching vn_stocks. (3) `vn_stocks`: `float(close)*scale` unrounded vs `Numeric(20,6)` — 16.10*1000
= 16100.000000000002 ⇒ same false-conflict batch block; 46/2801 real HOSE ticks (1.6%) hit it.
Now `round(...,6)` like yahoo.py. Invisible to tests because SQLite doesn't apply Numeric rounding.
(4) `mechanistic_fourier`: guard was `np.all(raw<=0)` but the path is renormalised by `raw[0]` —
a negative first month made `scale` negative and FLIPPED THE SIGN of every point (verified:
[-4,30,60] ⇒ [100,100,-750,-750,-1500,-1500], lower>upper bands, -1600% would top the bulletin's
"GIẢM mạnh nhất"). Now `np.any` ⇒ fail closed to flat anchor. Auto-enabled in prod when a
commodity has supply drivers. (5) `write_forecast_log`: per-commodity `except Exception` ate
DBAPIError; with pool_pre_ping the run recovers, inserts a partial day and exits 0 GREEN, and the
evaluator then scores a biased subset. Now propagates, as weekly_movers already does.
(6) `evaluate_forecast_log --limit 0` was falsy ⇒ dropped the LIMIT and would flip EVERY matured
pending row in one one-way commit. Rejected with exit 2. Plus docs: PLAN §2/README/ARCHITECTURE
inventory re-measured (52 profiles = 22+30 / 100 instruments — 51/98 was stale since PEPPER_VN
+ DIESEL_VN); PLAN §6 web polish cleared (eslint CLI, outputFileTracingRoot, `npm audit fix`
no-force: 5/8 advisories cleared in-range).
**Gates:** pytest 588→**594 passed + 1 skip** · ruff 0 · mypy 0 (28+34) · workflows 5/5 ·
vitest 39 · tsc/eslint/next build clean. No DB, no network, no deploy, no `--write` (container
has no `.env`).
**ESCALATED — needs owner decision, deliberately NOT changed:** (a) `--backfill`/`--csv-import`
commit with NO `--write` (INV-7 breach), and the dry-run path commits `seed_ingestion_sources`
first — but `.github/workflows/ingest.yml` (5 call sites) DEPENDS on that write, so fixing it
without adding `--write` there stops the daily ingest. (b) `POST /forecast` has no internal-key
gate while its GET twin does — and `test_forecast_api_gate.py:81-85` PINS the ungated behaviour,
so this is a design decision, not a slip. (c) `ml/runner.py` backtests the forward-filled
calendar-day MV and picks the LOWEST instrument_key, while `/forecast` serves the instrument with
the most price dates — so `/models/best` can advertise a MAPE from a different series than
production uses; registry promotion also lacks `SWITCH_MARGIN`, so it registers models
`/forecast` will never pick. (d) `cash_flow_predictor` slices `q_future` positionally from a
date-sorted frame, making the configured 6-month harvest lag act as 5 (verified: +9.09 = exactly
one month of planted area). (e) Restatement accepts a reload covering only 90% of stored dates —
can silently shorten served history; sits inside the approval-gated VN30-PROD area.
**Rules distilled:** (1) A test that pins a clock-dependent code path must inject or relativise
the date — an absolute fixture date is a time bomb, not a pin. (2) SQLite-backed writer tests
cannot see `Numeric(p,s)` rounding, so any float written to a Numeric column needs rounding at
the source (there is now a precedent in yahoo/vn_stocks — follow it for new connectors).
(3) When a trajectory is renormalised by its first element, guards must be `any`, not `all`.

## 2026-09-03 WEB-POLISH-1 — WEB_POLISH_1_PASS (local only; not pushed)
Cleared PLAN.md §6 deferred-polish items: (1) `apps/web/next.config.mjs` sets
`outputFileTracingRoot` (repo-root Cloudflare-worker `package-lock.json` was making Next
misdetect the workspace root — build warning confirmed present before, gone after);
(2) `apps/web` `lint` script + `.github/workflows/ci.yml` step moved `next lint` →
`eslint .` (deprecated in Next 16) — added `ignorePatterns` (`.next/**`, `next-env.d.ts`,
`coverage/**`, `node_modules/**`) to `.eslintrc.json` since plain eslint, unlike `next
lint`, doesn't auto-skip the generated `next-env.d.ts` triple-slash reference;
(3) `npm audit fix` (no `--force`) in `apps/web` — 5/8 vulnerabilities cleared in-range
(browserslist, js-yaml, nanoid, sharp, brace-expansion; `next` patch-bumped
15.5.19→15.5.25 within its own `^15.5.19` range) — lockfile-only diff, `package.json`
deps unchanged. Remaining 3 (postcss/esbuild/next high-severity range) need a Next 16
major — deliberately NOT force-fixed; recorded as its own approval-gated item in
PLAN.md §6, not attempted here.
Gates run (apps/web touched): vitest 39 passed (matches PLAN §2 baseline, unchanged) ·
`tsc --noEmit` clean · `eslint .` clean · `next build` clean (workspace-root warning
gone). Python side untouched — no repo-root gates re-run (nothing outside apps/web
changed).
**Rules distilled:** (1) `npm audit fix` without `--force` is safe to run unattended —
it only moves within declared semver ranges; always diff `package.json` after to confirm
(here: lockfile-only). (2) migrating off `next lint` needs explicit `ignorePatterns` for
generated files (`next-env.d.ts`) that `next lint` silently skipped.

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
