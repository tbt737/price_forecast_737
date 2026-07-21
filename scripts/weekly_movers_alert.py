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
from datetime import UTC, datetime, timedelta
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
                   generated_at_utc: datetime, scanned: int, unavailable: int) -> str:
    """Plain-text weekly bulletin (Vietnamese). Hard-truncated under Telegram's 4096-char
    limit so a pure-YAML count increase can never turn delivery red."""
    ict = generated_at_utc + timedelta(hours=7)
    data_through = max((m.last_date for rows in sections.values() for m in rows), default="?")
    lines = [
        f"📊 BẢN TIN DỰ BÁO TUẦN — {ict.strftime('%d/%m/%Y %H:%M')} {cfg.timezone_note}",
        f"(quét {scanned} mã, {unavailable} mã không dự báo được; chân trời "
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

    def send(self, message: str) -> tuple[list[str], list[str]]:
        """Deliver to ALL usable channels independently — one channel failing must not
        abort the others (dual-channel redundancy) and the partial-delivery record must
        survive. Returns (delivered, failed) channel names; failures are reported by
        exception CLASS only, so no credential can leak into logs."""
        delivered: list[str] = []
        failed: list[str] = []
        for channel in self.usable_channels():
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
                failed.append(channel)
            else:
                delivered.append(channel)
        return delivered, failed


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
    if scanned and unavailable / scanned > 0.5:
        # More than half the universe failing to forecast is systemic (engine or data
        # regression), not per-asset noise — refuse to publish a misleading ranking.
        print(f"[weekly-movers] {unavailable}/{scanned} assets unforecastable — systemic failure, refusing to send")
        return 1

    sections = rank_movers(movers, cfg)
    message = format_message(
        sections, cfg, generated_at_utc=datetime.now(UTC), scanned=scanned, unavailable=unavailable
    )
    print(message)

    if not args.send:
        print("\n[weekly-movers] DRY-RUN — nothing sent (pass --send to deliver)")
        return 0

    notifier = Notifier(cfg)
    if not notifier.usable_channels():
        print("[weekly-movers] --send but NO channel has complete credentials — failing closed")
        return 1
    delivered, failed = notifier.send(message)
    print(f"[weekly-movers] delivered via: {', '.join(delivered) or '(none)'}"
          + (f" | FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed or not delivered else 0


if __name__ == "__main__":
    raise SystemExit(main())
