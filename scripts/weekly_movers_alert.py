"""Weekly movers alert — rank every forecastable asset by expected move and notify.

Config-over-code: counts/horizon/channels live in ``configs/alerts/weekly_movers.yaml``;
assets are discovered from ``dim_commodity`` (equities = ``commodity_group == 'equity'``,
commodities = everything else) — no ticker is ever hardcoded here.

Read path only: the ranking calls the same production forecaster
(``ml.forecast.forecast_commodity``) the API serves; nothing is written to the DB.

DRY-RUN BY DEFAULT (prints the message). ``--send`` delivers via every channel whose
credentials are fully present in the environment:
  * Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  * Email:    ALERT_SMTP_HOST/PORT/USER/PASSWORD + ALERT_EMAIL_FROM/TO
``--send`` with zero usable channels exits 1 (fail closed — a mis-secreted cron must
turn red, not silently print into a log nobody reads). Credentials are never logged.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "apps" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# The bulletin contains emoji/Vietnamese; a cp1252 Windows console must not crash
# the dry-run (GitHub Actions runners are UTF-8 already).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yaml  # noqa: E402

CONFIG_PATH = REPO_ROOT / "configs" / "alerts" / "weekly_movers.yaml"


@dataclass(frozen=True)
class AlertConfig:
    horizon_days: int = 30
    up_commodities: int = 5
    up_equities: int = 5
    down_commodities: int = 3
    down_equities: int = 3
    telegram_enabled: bool = True
    email_enabled: bool = True
    timezone_note: str = "giờ Việt Nam (ICT)"
    disclaimer: str = "Dự báo thống kê trên chuỗi giá lịch sử — KHÔNG phải lời khuyên đầu tư."
    # Freshness gate (trading days, NOT calendar days — weekends/holidays must not
    # trip it): refuse to send when the freshest data lags "now" by more than
    # max_lag_trading_days; exclude any asset whose own data lags the freshest
    # asset by more than max_asset_skew_trading_days (mixed-as-of guard).
    max_lag_trading_days: int = 3
    max_asset_skew_trading_days: int = 5


def load_alert_config(path: Path = CONFIG_PATH) -> AlertConfig:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    up = data.get("top_up", {}) or {}
    down = data.get("top_down", {}) or {}
    ch = data.get("channels", {}) or {}
    return AlertConfig(
        horizon_days=int(data.get("horizon_days", 30)),
        up_commodities=int(up.get("commodities", 5)),
        up_equities=int(up.get("equities", 5)),
        down_commodities=int(down.get("commodities", 3)),
        down_equities=int(down.get("equities", 3)),
        telegram_enabled=bool((ch.get("telegram") or {}).get("enabled", True)),
        email_enabled=bool((ch.get("email") or {}).get("enabled", True)),
        timezone_note=str(data.get("timezone_note", "giờ Việt Nam (ICT)")),
        disclaimer=str(data.get("disclaimer", AlertConfig.disclaimer)),
        max_lag_trading_days=int((data.get("freshness") or {}).get("max_lag_trading_days", 3)),
        max_asset_skew_trading_days=int(
            (data.get("freshness") or {}).get("max_asset_skew_trading_days", 5)
        ),
    )


@dataclass(frozen=True)
class Mover:
    """One ranked asset — everything the message needs, nothing more."""

    commodity_code: str
    commodity_name: str
    is_equity: bool
    pct_move: float  # expected % change over the horizon (point forecast vs last close)
    last_price: float
    currency: str
    model_used: str
    mape_pct: float | None
    naive_mape_pct: float | None
    beats_naive: bool
    last_date: str


def rank_movers(movers: list[Mover], cfg: AlertConfig) -> dict[str, list[Mover]]:
    """Split into the four report sections. Up-lists take only POSITIVE expected moves,
    down-lists only NEGATIVE ones (an 'up' list padded with falling assets would lie);
    sections may therefore hold fewer entries than configured."""
    eq = [m for m in movers if m.is_equity]
    co = [m for m in movers if not m.is_equity]

    def top(items: list[Mover], n: int, *, up: bool) -> list[Mover]:
        pool = [m for m in items if (m.pct_move > 0 if up else m.pct_move < 0)]
        pool.sort(key=lambda m: m.pct_move, reverse=up)
        return pool[:n]

    return {
        "up_commodities": top(co, cfg.up_commodities, up=True),
        "up_equities": top(eq, cfg.up_equities, up=True),
        "down_commodities": top(co, cfg.down_commodities, up=False),
        "down_equities": top(eq, cfg.down_equities, up=False),
    }


def _fmt_price(value: float, currency: str) -> str:
    return f"{value:,.0f} {currency}" if value >= 1000 else f"{value:,.2f} {currency}"


def _fmt_line(rank: int, m: Mover) -> str:
    bt = ""
    if m.mape_pct is not None and m.naive_mape_pct is not None:
        mark = "✓" if m.beats_naive else "≈naive"
        bt = f", MAPE {m.mape_pct:.1f}% vs naive {m.naive_mape_pct:.1f}% {mark}"
    return (
        f"{rank}. {m.commodity_code} {m.pct_move:+.1f}%"
        f" — {_fmt_price(m.last_price, m.currency)} ({m.model_used}{bt})"
    )


TELEGRAM_LIMIT = 4096


def format_message(sections: dict[str, list[Mover]], cfg: AlertConfig, *,
                   generated_at_utc: datetime, scanned: int, unavailable: int,
                   stale: int = 0) -> str:
    """Plain-text weekly bulletin (Vietnamese). Hard-truncated under Telegram's 4096-char
    limit so a pure-YAML count increase can never turn delivery red."""
    ict = generated_at_utc + timedelta(hours=7)
    data_through = max((m.last_date for rows in sections.values() for m in rows), default="?")
    stale_note = f", {stale} mã bị loại vì dữ liệu cũ" if stale else ""
    lines = [
        f"📊 BẢN TIN DỰ BÁO TUẦN — {ict.strftime('%d/%m/%Y %H:%M')} {cfg.timezone_note}",
        f"(quét {scanned} mã, {unavailable} mã không dự báo được{stale_note}; chân trời "
        f"{cfg.horizon_days} phiên; dữ liệu đến {data_through})",
        "",
    ]
    blocks = [
        ("📈 TĂNG mạnh nhất — HÀNG HÓA", "up_commodities"),
        ("📈 TĂNG mạnh nhất — CỔ PHIẾU", "up_equities"),
        ("📉 GIẢM mạnh nhất — HÀNG HÓA", "down_commodities"),
        ("📉 GIẢM mạnh nhất — CỔ PHIẾU", "down_equities"),
    ]
    for title, key in blocks:
        lines.append(title + ":")
        rows = sections.get(key) or []
        if not rows:
            lines.append("  (không có mã nào theo hướng này)")
        else:
            lines.extend("  " + _fmt_line(i, m) for i, m in enumerate(rows, 1))
        lines.append("")
    lines.append(f"⚠️ {cfg.disclaimer}")
    message = "\n".join(lines)
    if len(message) > TELEGRAM_LIMIT:  # keep the disclaimer, cut the middle
        tail = f"\n… (rút gọn vì vượt giới hạn tin nhắn)\n⚠️ {cfg.disclaimer}"
        message = message[: TELEGRAM_LIMIT - len(tail)] + tail
    return message


# ── freshness (trading days, not calendar days) ──────────────────────────────
def trading_days_between(start: date, end: date) -> int:
    """Weekdays strictly after ``start`` up to and including ``end`` (0 if end<=start).
    Weekend-aware so Friday→Monday is 1 trading day, never 3 stale days. (Exchange
    holidays are counted as trading days — the gate is deliberately conservative:
    a long holiday can only make it stricter, never let stale data through.)"""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def apply_freshness(
    movers: list[Mover], cfg: AlertConfig, *, today: date
) -> tuple[list[Mover], list[Mover], int]:
    """(fresh_movers, stale_skipped, global_lag_trading_days). Global staleness is
    decided by the CALLER (refuse when lag > cfg.max_lag_trading_days); per-asset
    skew is filtered here so one lagging feed cannot mix old as-of into the ranking."""
    if not movers:
        return [], [], 0
    dates = [date.fromisoformat(m.last_date) for m in movers if m.last_date]
    if not dates:  # engine-contract violation: no mover carries a data date
        return [], list(movers), 999
    latest = max(dates)
    global_lag = trading_days_between(latest, today)
    fresh, stale = [], []
    for m in movers:
        skew = trading_days_between(date.fromisoformat(m.last_date), latest) if m.last_date else 999
        (fresh if skew <= cfg.max_asset_skew_trading_days else stale).append(m)
    return fresh, stale, global_lag


# ── idempotency / delivery record (isolated ops table; never touches market data) ──
DELIVERY_DDL = """CREATE TABLE IF NOT EXISTS alert_delivery_log (
    period_key     VARCHAR(80)  NOT NULL,
    channel        VARCHAR(20)  NOT NULL,
    destination_fp VARCHAR(16)  NOT NULL,
    status         VARCHAR(12)  NOT NULL,
    detail         VARCHAR(200),
    created_at     TIMESTAMP    NOT NULL,
    updated_at     TIMESTAMP    NOT NULL,
    PRIMARY KEY (period_key, channel, destination_fp)
)"""


def _fp(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def period_key(cfg: AlertConfig, *, now_utc: datetime) -> str:
    """Stable per-bulletin-period key: ISO year+week (in ICT — the audience's week)
    plus a config fingerprint. Reruns/retries of the same week share the key; a
    config change (different bulletin) legitimately gets a new one. Never derived
    from workflow_run_id (a rerun is a NEW run but the SAME bulletin)."""
    ict = now_utc + timedelta(hours=7)
    ict_date = ict.date()
    if ict_date.weekday() == 6:  # Sunday ICT rolls FORWARD: the bulletin is a
        ict_date += timedelta(days=1)  # Monday-anchored product — a Sunday-evening
        # manual send belongs to the coming week, closing the Sun/Mon double-send window.
    iso = ict_date.isocalendar()
    cfg_fp = _fp(
        f"{cfg.horizon_days}:{cfg.up_commodities}:{cfg.up_equities}"
        f":{cfg.down_commodities}:{cfg.down_equities}"
    )[:8]
    return f"weekly-movers:{iso.year}-W{iso.week:02d}:{cfg_fp}"


class DeliveryLog:
    """Claim-first delivery record on the isolated ``alert_delivery_log`` table.

    Rerun semantics (the anti-duplicate invariant):
      * delivered → SKIP (a subscriber never gets the same weekly bulletin twice)
      * pending   → SKIP + warn (a crashed in-flight send is ambiguous — the message
                    may have reached the provider; a human decides, we never guess)
      * failed    → RETRY (per-channel retry without re-sending the healthy channel)
      * no row    → claim (INSERT pending); a concurrent claimer loses on the PK
                    and is treated as SKIP — two near-simultaneous runs cannot both send.
    Dry-runs never touch the table, so they cannot burn a live period key."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def _pg(self) -> bool:
        """On PostgreSQL the runner has NO direct table rights — every access goes
        through the SECURITY DEFINER functions of migration 007 (least privilege).
        The direct-SQL path below exists for SQLite (offline tests) only."""
        try:
            return str(self._s.get_bind().dialect.name) == "postgresql"
        except Exception:  # noqa: BLE001 — fakes in tests may lack get_bind
            return False

    def ensure_table(self) -> None:
        from sqlalchemy import text

        if self._pg():
            # Probe the 007 interface instead of running DDL (the runner cannot and
            # must not CREATE): a missing function is a clear, actionable failure.
            try:
                self._s.execute(text("SELECT alert_status('probe', 'telegram', 'probe')"))
                self._s.rollback()
            except Exception as exc:
                self._s.rollback()
                raise RuntimeError(
                    "alert delivery interface missing — apply db/migrations/006 and 007"
                ) from exc
            return
        self._s.execute(text(DELIVERY_DDL))
        self._s.commit()

    def status(self, key: str, channel: str, dest_fp: str) -> str | None:
        from sqlalchemy import text

        if self._pg():
            row = self._s.execute(
                text("SELECT alert_status(:k, :c, :d)"),
                {"k": key, "c": channel, "d": dest_fp},
            ).scalar_one_or_none()
            self._s.rollback()
            return None if row is None else str(row)
        row = self._s.execute(
            text("SELECT status FROM alert_delivery_log WHERE period_key = :k "
                 "AND channel = :c AND destination_fp = :d"),
            {"k": key, "c": channel, "d": dest_fp},
        ).first()
        return None if row is None else str(row[0])

    def claim(self, key: str, channel: str, dest_fp: str) -> bool:
        """True iff WE claimed it (row inserted as pending). A lost race or an
        existing non-failed row means the caller must not send."""
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        if self._pg():  # atomic CAS + race-safe insert live INSIDE alert_claim()
            claimed = bool(self._s.execute(
                text("SELECT alert_claim(:k, :c, :d)"),
                {"k": key, "c": channel, "d": dest_fp},
            ).scalar_one())
            self._s.commit()
            return claimed

        existing = self.status(key, channel, dest_fp)
        now = datetime.now(UTC).replace(tzinfo=None)
        if existing == "failed":  # per-channel retry: re-arm via compare-and-set —
            # two racers may both READ 'failed', but only the one whose UPDATE actually
            # flips the row (rowcount 1) wins the claim; the loser must not send.
            result = self._s.execute(
                text("UPDATE alert_delivery_log SET status = 'pending', updated_at = :t "
                     "WHERE period_key = :k AND channel = :c AND destination_fp = :d "
                     "AND status = 'failed'"),
                {"t": now, "k": key, "c": channel, "d": dest_fp},
            )
            self._s.commit()
            return bool(getattr(result, "rowcount", 0) == 1)
        if existing is not None:
            return False  # delivered or pending ⇒ never double-send
        try:
            self._s.execute(
                text("INSERT INTO alert_delivery_log "
                     "(period_key, channel, destination_fp, status, detail, created_at, updated_at) "
                     "VALUES (:k, :c, :d, 'pending', NULL, :t, :t)"),
                {"k": key, "c": channel, "d": dest_fp, "t": now},
            )
            self._s.commit()
            return True
        except IntegrityError:  # concurrent run claimed first
            self._s.rollback()
            return False

    def mark(self, key: str, channel: str, dest_fp: str, status: str, detail: str = "") -> None:
        from sqlalchemy import text

        if self._pg():  # only pending→delivered|failed exists server-side
            self._s.execute(
                text("SELECT alert_mark(:k, :c, :d, :s, :dt)"),
                {"k": key, "c": channel, "d": dest_fp, "s": status, "dt": detail[:200]},
            )
            self._s.commit()
            return
        self._s.execute(
            text("UPDATE alert_delivery_log SET status = :s, detail = :dt, updated_at = :t "
                 "WHERE period_key = :k AND channel = :c AND destination_fp = :d"),
            {"s": status, "dt": detail[:200], "t": datetime.now(UTC).replace(tzinfo=None),
             "k": key, "c": channel, "d": dest_fp},
        )
        self._s.commit()


# ── delivery (credentials from env only; transports injectable for tests) ────
TelegramPost = Callable[[str, dict[str, str]], None]


def _telegram_post(url: str, payload: dict[str, str]) -> None:
    # urllib on purpose: str(urllib.error.HTTPError) does NOT embed the URL, so the
    # bot token (which lives in the URL) cannot leak into a traceback. `requests`
    # exceptions DO embed the full URL — do not "modernize" this transport.
    import urllib.request

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed API host
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not body.get("ok", False):
        raise RuntimeError(f"telegram API returned ok={body.get('ok')}")


@dataclass
class Notifier:
    """Sends to every channel with COMPLETE credentials; reports what it used."""

    cfg: AlertConfig
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    telegram_post: TelegramPost = _telegram_post
    smtp_factory: Callable[[str, int], Any] = smtplib.SMTP

    def usable_channels(self) -> list[str]:
        out = []
        if self.cfg.telegram_enabled and self.env.get("TELEGRAM_BOT_TOKEN") and self.env.get("TELEGRAM_CHAT_ID"):
            out.append("telegram")
        if self.cfg.email_enabled and all(
            self.env.get(k)
            for k in ("ALERT_SMTP_HOST", "ALERT_SMTP_PORT", "ALERT_SMTP_USER",
                      "ALERT_SMTP_PASSWORD", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO")
        ):
            out.append("email")
        return out

    def destination_fp(self, channel: str) -> str:
        """Truncated hash of the destination — safe to store/log, never reversible."""
        raw = self.env.get("TELEGRAM_CHAT_ID", "") if channel == "telegram" else self.env.get("ALERT_EMAIL_TO", "")
        return _fp(raw)

    def send(
        self, message: str, *, log: DeliveryLog | None = None, key: str = ""
    ) -> tuple[list[str], list[str], list[str]]:
        """Deliver to ALL usable channels independently — one channel failing must not
        abort the others, and the partial-delivery record must survive. With a
        DeliveryLog, each channel is CLAIMED before sending (rerun of the same period
        skips already-delivered/in-flight channels and retries only failed ones).
        Returns (delivered, failed, skipped); failures are reported by exception CLASS
        only, so no credential can leak into logs."""
        delivered: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        for channel in self.usable_channels():
            dest = self.destination_fp(channel)
            if log is not None and not log.claim(key, channel, dest):
                state = log.status(key, channel, dest) or "unknown"
                print(f"[weekly-movers] {channel}: dedupe skip for {key} (record: {state}"
                      + ("; a stuck 'pending' means a crashed in-flight send — see "
                         "db/migrations/006 for the un-stick procedure)" if state == "pending" else ")"))
                skipped.append(channel)
                continue
            try:
                if channel == "telegram":
                    token = self.env["TELEGRAM_BOT_TOKEN"]
                    self.telegram_post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": self.env["TELEGRAM_CHAT_ID"], "text": message},
                    )
                elif channel == "email":
                    msg = MIMEText(message, _charset="utf-8")
                    msg["Subject"] = "Bản tin dự báo tuần — Multi-Commodity Quant Forecasting"
                    msg["From"] = self.env["ALERT_EMAIL_FROM"]
                    msg["To"] = self.env["ALERT_EMAIL_TO"]
                    with self.smtp_factory(self.env["ALERT_SMTP_HOST"], int(self.env["ALERT_SMTP_PORT"])) as s:
                        s.starttls()
                        s.login(self.env["ALERT_SMTP_USER"], self.env["ALERT_SMTP_PASSWORD"])
                        s.send_message(msg)
            except Exception as exc:  # noqa: BLE001 — isolate channels; class name only
                print(f"[weekly-movers] channel {channel} FAILED: {type(exc).__name__}")
                if log is not None:
                    log.mark(key, channel, dest, "failed", type(exc).__name__)
                failed.append(channel)
            else:
                if log is not None:
                    log.mark(key, channel, dest, "delivered")
                delivered.append(channel)
        return delivered, failed, skipped


# ── compute (read-only against the platform DB) ──────────────────────────────
def collect_movers(session: Any, cfg: AlertConfig, *, limit: int | None = None) -> tuple[list[Mover], int, int]:
    """Forecast every commodity and build the Mover list. Returns (movers, scanned,
    unavailable). Unavailable (too little history / engine failure) is counted, never
    fatal — one broken asset must not kill the whole bulletin."""
    from app.models import DimCommodity
    from sqlalchemy import select

    from ml.forecast import forecast_commodity

    rows = list(session.execute(select(DimCommodity).order_by(DimCommodity.commodity_code)).scalars())
    if limit is not None:
        rows = rows[:limit]
    from sqlalchemy.exc import DBAPIError, InvalidRequestError

    movers: list[Mover] = []
    unavailable = 0
    for c in rows:
        try:
            result = forecast_commodity(session, c.commodity_code, horizons=(cfg.horizon_days,))
        except (DBAPIError, InvalidRequestError):
            # Infrastructure failure (connection dropped, session poisoned): every later
            # asset would fail too — a partial bulletin mislabeled as "không dự báo
            # được" must NEVER be sent. Abort loudly instead (red run).
            raise
        except Exception:  # noqa: BLE001 — a single asset's engine failure is non-fatal
            unavailable += 1
            continue
        if not result.get("available"):
            unavailable += 1
            continue
        hz = (result.get("horizons") or {}).get(str(cfg.horizon_days))
        last_price = result.get("last_price")
        if not hz or not hz.get("points") or not last_price:
            unavailable += 1
            continue
        end_value = float(hz["points"][-1]["value"])
        bt = hz.get("backtest") or {}
        movers.append(
            Mover(
                commodity_code=c.commodity_code,
                commodity_name=c.commodity_name,
                is_equity=str(getattr(c.commodity_group, "value", c.commodity_group)) == "equity",
                pct_move=(end_value / float(last_price) - 1.0) * 100.0,
                last_price=float(last_price),
                currency=c.default_currency or "",
                model_used=str(hz.get("model_used", "?")),
                mape_pct=bt.get("mape_pct"),
                naive_mape_pct=bt.get("naive_mape_pct"),
                beats_naive=bool(bt.get("beats_naive", False)),
                last_date=str(result.get("last_date", "")),
            )
        )
    return movers, len(rows), unavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly movers alert (dry-run by default).")
    parser.add_argument("--send", action="store_true", help="actually deliver (default: print only)")
    parser.add_argument("--limit", type=int, default=None, help="only scan the first N commodities (smoke)")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")

    cfg = load_alert_config(args.config)

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        movers, scanned, unavailable = collect_movers(session, cfg, limit=args.limit)
    finally:
        session.close()

    if not movers:
        print(f"[weekly-movers] no forecastable assets (scanned={scanned}); refusing to send an empty bulletin")
        return 1

    # Freshness gate (trading-day aware): stale global data or a >50% failure/stale
    # ratio means the bulletin would mislead — fail closed, red run, nothing sent.
    now_utc = datetime.now(UTC)
    today_ict = (now_utc + timedelta(hours=7)).date()
    movers, stale_movers, global_lag = apply_freshness(movers, cfg, today=today_ict)
    if global_lag > cfg.max_lag_trading_days:
        print(f"[weekly-movers] freshest data lags {global_lag} trading days "
              f"(> {cfg.max_lag_trading_days}) — ingest looks broken, refusing to send")
        return 1
    if stale_movers:
        print("[weekly-movers] stale (excluded): "
              + ", ".join(m.commodity_code for m in stale_movers))
    if scanned and (unavailable + len(stale_movers)) / scanned > 0.5:
        # More than half the universe failing/stale is systemic (engine or data
        # regression), not per-asset noise — refuse to publish a misleading ranking.
        print(f"[weekly-movers] {unavailable} unforecastable + {len(stale_movers)} stale "
              f"of {scanned} — systemic failure, refusing to send")
        return 1
    if not movers:
        print("[weekly-movers] all assets stale — refusing to send")
        return 1

    sections = rank_movers(movers, cfg)
    message = format_message(
        sections, cfg, generated_at_utc=now_utc, scanned=scanned,
        unavailable=unavailable, stale=len(stale_movers),
    )
    print(message)

    if not args.send:
        # Dry-run never touches the delivery log — it cannot burn a live period key.
        print("\n[weekly-movers] DRY-RUN — nothing sent (pass --send to deliver)")
        return 0

    notifier = Notifier(cfg)
    if not notifier.usable_channels():
        print("[weekly-movers] --send but NO channel has complete credentials — failing closed")
        return 1

    key = period_key(cfg, now_utc=now_utc)
    log_session = get_session_factory()()
    try:
        log = DeliveryLog(log_session)
        log.ensure_table()
        delivered, failed, skipped = notifier.send(message, log=log, key=key)
    finally:
        log_session.close()
    print(f"[weekly-movers] {key} | delivered: {', '.join(delivered) or '(none)'}"
          + (f" | FAILED: {', '.join(failed)}" if failed else "")
          + (f" | deduped: {', '.join(skipped)}" if skipped else ""))
    if failed:
        return 1
    if delivered:
        return 0
    # nothing delivered: pure dedupe rerun is SUCCESS; anything else is a failure
    return 0 if skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
