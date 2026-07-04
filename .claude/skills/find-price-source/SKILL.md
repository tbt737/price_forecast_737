---
name: find-price-source
description: Discover and validate where a commodity's daily price lives online before onboarding it. Ranks Yahoo Finance tickers, public JSON APIs, HTML scrapes, and user CSVs; probes candidate URLs; detects Cloudflare blocks; classifies JSON vs HTML; and captures a fixture. Use when you need an online price source for a commodity, want to know if a URL is scrapeable, or are finding Vietnamese domestic prices (vàng/bạc/thép/inox — "đi tìm giá cả online"). Feeds the add-commodity skill.
---

# Find an online price source

Goal: return a **usable daily-price endpoint** + the parsing shape + a captured fixture,
or an honest "no stable source — recommend CSV / accumulate-forward".

## Source tiers (prefer the top)
1. **Yahoo Finance ticker** (futures/ETF) — long clean history, point-in-time safe, already
   the platform's main path. Best when it exists. Verify a candidate ticker actually returns
   data before committing it (`python -c "import yfinance,sys; print(yfinance.Ticker('SI=F').history(period='5d'))"`).
2. **Public JSON API** — clean, stable to parse. Best option for domestic spot prices.
3. **HTML scrape** — last resort; brittle. Find the page's underlying AJAX/partial endpoint
   instead of scraping the rendered page.
4. **User-provided CSV** — when nothing reliable exists online (recommend this for
   infrequently-published prices like domestic steel/inox).

## Probe procedure
Use the helper: `bash .claude/skills/find-price-source/probe.sh <url>`. It curls with a
browser User-Agent and classifies the response:
- **`Just a moment…` / `challenges.cloudflare`** → Cloudflare-protected, **skip** (don't
  fight it). Example: `sjc.com.vn` is blocked — use PNJ for gold instead.
- **starts with `{` or `[`** → JSON. Best. Note the price field names.
- **HTML** → grep the page for the data endpoint and hit *that*:
  `curl -s <page> | grep -oiE "url:[^,]+|/[A-Za-z]+/[A-Za-z]+Partial|/api/[A-Za-z/]+"`.
  Many sites load prices via an AJAX call to a JSON/partial route — prefer it.

## Known-good Vietnam domestic sources (verified working)
- **Gold (vàng)** — PNJ public JSON: `https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price`.
  Shape: `{"data":[{"masp":"SJC","giaban":<sell>,"giamua":<buy>}, …]}`. Pick by `masp`
  (`SJC` = vàng miếng, `N24K` = nhẫn 999.9); record `giaban` (giá bán ra).
- **Silver (bạc)** — Phú Quý ASP.NET partial:
  `https://giabac.phuquygroup.vn/PhuQuyPrice/SilverPricePartial` (send `X-Requested-With:
  XMLHttpRequest`). HTML table: `<td>name</td><td>unit</td><td>buy</td><td>sell</td>`;
  the **sell price (GIÁ BÁN RA) is the last numeric cell**. Entities like `&#218;`→Ú decode
  with `html.unescape`.
- **Steel / inox** — no stable free *daily* endpoint found: domestic prices are quote-based,
  updated weekly/monthly (cafef.vn reachable but sparse; SJC/VSA blocked or no API). Recommend
  a user CSV or accept a sparse weekly series — **do not fabricate a daily series**.

## After you find one
- **Capture a fixture** of the real response under `etl/tests/fixtures/<src>/` so connector
  tests run offline.
- Note the **unit** honestly (e.g. PNJ quotes in "thousand VND"). Record the source-published
  value **as-is**; do not rescale on a guess — document the unit in the profile `notes`.
- **History reality:** domestic spot endpoints give **today only**. There is no deep backfill —
  the series accumulates one point per day going forward. Tell the user before they expect a
  forecast; see the backfill-price-history skill.

Return: the endpoint URL, parser format (JSON field / HTML cell), the product key, currency,
unit caveat, the fixture path, and whether history is available or accrues forward.
