"""Offline tests for the weekly movers alert (ranking, formatting, delivery gating).

Pure — no DB, no network: transports are injected fakes; config is the real YAML.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scripts.weekly_movers_alert import (
    AlertConfig,
    Mover,
    Notifier,
    format_message,
    load_alert_config,
    rank_movers,
)


def _mover(code: str, pct: float, *, equity: bool, beats: bool = True) -> Mover:
    return Mover(
        commodity_code=code, commodity_name=code.title(), is_equity=equity,
        pct_move=pct, last_price=64_800.0, currency="VND", model_used="ridge_ar",
        mape_pct=8.1, naive_mape_pct=9.3, beats_naive=beats, last_date="2026-07-21",
    )


def _universe() -> list[Mover]:
    ups_eq = [_mover(f"EQU{i}_VN", 1.0 + i, equity=True) for i in range(7)]
    downs_eq = [_mover(f"EQD{i}_VN", -(1.0 + i), equity=True) for i in range(5)]
    ups_co = [_mover(f"COU{i}", 0.5 + i, equity=False) for i in range(6)]
    downs_co = [_mover(f"COD{i}", -(0.5 + i), equity=False) for i in range(4)]
    flat = [_mover("FLAT", 0.0, equity=False)]
    return ups_eq + downs_eq + ups_co + downs_co + flat


def test_config_loads_owner_defaults() -> None:
    cfg = load_alert_config()
    assert cfg.up_commodities == 5 and cfg.up_equities == 5
    assert cfg.down_commodities == 3 and cfg.down_equities == 3
    assert cfg.horizon_days == 30
    assert "không phải lời khuyên đầu tư" in cfg.disclaimer.lower()


def test_rank_movers_sections_counts_and_order() -> None:
    # explicit config — the ranking-semantics pin must not break when the owner
    # exercises the advertised YAML knobs
    cfg = AlertConfig(up_commodities=5, up_equities=5, down_commodities=3, down_equities=3)
    s = rank_movers(_universe(), cfg)
    assert [m.commodity_code for m in s["up_equities"]] == ["EQU6_VN", "EQU5_VN", "EQU4_VN", "EQU3_VN", "EQU2_VN"]
    assert [m.commodity_code for m in s["up_commodities"]] == ["COU5", "COU4", "COU3", "COU2", "COU1"]
    assert [m.commodity_code for m in s["down_equities"]] == ["EQD4_VN", "EQD3_VN", "EQD2_VN"]
    assert [m.commodity_code for m in s["down_commodities"]] == ["COD3", "COD2", "COD1"]
    # equity never leaks into the commodity section and vice versa
    assert all(m.is_equity for m in s["up_equities"] + s["down_equities"])
    assert all(not m.is_equity for m in s["up_commodities"] + s["down_commodities"])


def test_rank_movers_never_pads_with_wrong_direction() -> None:
    cfg = AlertConfig(up_commodities=5, down_commodities=3)
    only_down = [_mover("A", -2.0, equity=False), _mover("B", -1.0, equity=False)]
    s = rank_movers(only_down, cfg)
    assert s["up_commodities"] == []  # an "up" list must never contain a falling asset
    assert [m.commodity_code for m in s["down_commodities"]] == ["A", "B"]
    # flat (0.0%) belongs to NEITHER direction
    s2 = rank_movers([_mover("FLAT", 0.0, equity=False)], cfg)
    assert s2["up_commodities"] == [] and s2["down_commodities"] == []


def test_format_message_structure_and_limits() -> None:
    cfg = load_alert_config()
    s = rank_movers(_universe(), cfg)
    msg = format_message(s, cfg, generated_at_utc=datetime(2026, 7, 27, 2, 0, tzinfo=UTC),
                         scanned=66, unavailable=12)
    assert "BẢN TIN DỰ BÁO TUẦN — 27/07/2026 09:00" in msg  # 02:00 UTC rendered as ICT
    assert msg.count("TĂNG mạnh nhất") == 2 and msg.count("GIẢM mạnh nhất") == 2
    assert "EQU6_VN +7.0%" in msg and "COD3 -3.5%" in msg
    assert "không phải lời khuyên đầu tư" in msg.lower()
    assert len(msg) < 4096  # Telegram hard limit


def test_format_message_empty_section_is_explicit() -> None:
    cfg = load_alert_config()
    s = rank_movers([_mover("ONLY_UP", 2.0, equity=False)], cfg)
    msg = format_message(s, cfg, generated_at_utc=datetime.now(UTC), scanned=1, unavailable=0)
    assert "(không có mã nào theo hướng này)" in msg


# ── delivery gating (fail closed; injected transports; no secret leakage) ────
def test_notifier_no_credentials_means_no_channels() -> None:
    n = Notifier(AlertConfig(), env={})
    assert n.usable_channels() == []


def test_notifier_partial_credentials_do_not_count() -> None:
    n = Notifier(AlertConfig(), env={"TELEGRAM_BOT_TOKEN": "t"})  # chat_id missing
    assert n.usable_channels() == []
    n2 = Notifier(AlertConfig(), env={"ALERT_SMTP_HOST": "h", "ALERT_SMTP_PORT": "587"})
    assert n2.usable_channels() == []


def test_notifier_disabled_channel_is_skipped_even_with_credentials() -> None:
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    assert Notifier(AlertConfig(telegram_enabled=False), env=env).usable_channels() == []


def test_notifier_telegram_send_uses_token_in_url_not_in_payload() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    env = {"TELEGRAM_BOT_TOKEN": "SECRET-TOKEN", "TELEGRAM_CHAT_ID": "42"}
    n = Notifier(AlertConfig(email_enabled=False), env=env,
                 telegram_post=lambda url, payload: calls.append((url, payload)))
    delivered, failed, skipped = n.send("hello bulletin")
    assert delivered == ["telegram"] and failed == [] and skipped == []
    # plain-text delivery on purpose: no parse_mode ⇒ Telegram cannot interpret any
    # asset name/HTML fragment as markup (content-escaping by construction)
    assert "parse_mode" not in calls[0][1]
    (url, payload), = calls
    assert url == "https://api.telegram.org/botSECRET-TOKEN/sendMessage"
    assert payload == {"chat_id": "42", "text": "hello bulletin"}
    assert "SECRET-TOKEN" not in payload["text"]  # token never enters the message body


class _FakeSMTP:
    """Records the send; supports the context-manager + starttls/login protocol."""

    sent: list[object] = []
    logins: list[tuple[str, str]] = []

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None: ...

    def login(self, user: str, password: str) -> None:
        _FakeSMTP.logins.append((user, password))

    def send_message(self, msg: object) -> None:
        _FakeSMTP.sent.append(msg)


_EMAIL_ENV = {
    "ALERT_SMTP_HOST": "smtp.example.com", "ALERT_SMTP_PORT": "587",
    "ALERT_SMTP_USER": "u", "ALERT_SMTP_PASSWORD": "SECRET-PW",
    "ALERT_EMAIL_FROM": "bot@example.com", "ALERT_EMAIL_TO": "owner@example.com",
}


def test_notifier_email_branch_sends_via_injected_smtp() -> None:
    _FakeSMTP.sent, _FakeSMTP.logins = [], []
    n = Notifier(AlertConfig(telegram_enabled=False), env=dict(_EMAIL_ENV), smtp_factory=_FakeSMTP)
    delivered, failed, skipped = n.send("bulletin body")
    assert delivered == ["email"] and failed == [] and skipped == []
    assert len(_FakeSMTP.sent) == 1 and _FakeSMTP.logins == [("u", "SECRET-PW")]
    assert "SECRET-PW" not in str(_FakeSMTP.sent[0])  # password never in the message


def test_notifier_email_disabled_is_skipped_even_with_credentials() -> None:
    n = Notifier(AlertConfig(email_enabled=False), env=dict(_EMAIL_ENV), smtp_factory=_FakeSMTP)
    assert n.usable_channels() == []


def test_notifier_one_channel_failure_does_not_abort_the_other() -> None:
    def boom(url: str, payload: dict[str, str]) -> None:
        raise RuntimeError("telegram down")

    _FakeSMTP.sent = []
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c", **_EMAIL_ENV}
    n = Notifier(AlertConfig(), env=env, telegram_post=boom, smtp_factory=_FakeSMTP)
    delivered, failed, _skipped = n.send("x")
    assert failed == ["telegram"] and delivered == ["email"]  # email still went out
    assert len(_FakeSMTP.sent) == 1


def test_format_message_truncates_over_telegram_limit() -> None:
    from scripts.weekly_movers_alert import TELEGRAM_LIMIT

    cfg = AlertConfig(up_commodities=200, up_equities=200, down_commodities=200, down_equities=200)
    many = [_mover(f"VERY_LONG_COMMODITY_CODE_{i:04d}_VN", 0.1 + i, equity=False) for i in range(300)]
    s = rank_movers(many, cfg)
    msg = format_message(s, cfg, generated_at_utc=datetime.now(UTC), scanned=300, unavailable=0)
    assert len(msg) <= TELEGRAM_LIMIT
    assert msg.rstrip().endswith(cfg.disclaimer)  # disclaimer survives truncation


# ── collect_movers + main (offline: stubbed forecaster, fake session) ────────
def _forecast_stub(pct: float, *, available: bool = True, model: str = "ridge_ar"):
    def stub(session, code, *, horizons):
        if not available:
            return {"available": False, "reason": "need >= 252"}
        h = str(horizons[0])
        return {
            "available": True, "last_price": 100.0, "last_date": "2026-07-21",
            "horizons": {h: {
                "model_used": model,
                "points": [{"date": "2026-08-01", "value": 100.0 * (1 + pct / 100.0)}],
                "backtest": {"mape_pct": 5.0, "naive_mape_pct": 6.0, "beats_naive": True},
            }},
        }

    return stub


class _FakeRow:
    def __init__(self, code: str, group: str) -> None:
        self.commodity_code = code
        self.commodity_name = code
        self.commodity_group = group
        self.default_currency = "USD"


class _FakeSession:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def execute(self, _stmt):
        rows = self._rows

        class _R:
            def scalars(self) -> list[_FakeRow]:
                return rows

        return _R()

    def close(self) -> None: ...


def test_collect_movers_math_split_and_unavailable(monkeypatch) -> None:
    import ml.forecast as mlf
    from scripts.weekly_movers_alert import collect_movers

    calls = {}

    def stub(session, code, *, horizons):
        calls[code] = horizons
        if code == "DEAD":
            raise ValueError("engine broke for one asset")
        if code == "THIN":
            return {"available": False, "reason": "need >= 252"}
        return _forecast_stub(+7.5 if code == "EQ_VN" else -2.0)(session, code, horizons=horizons)

    monkeypatch.setattr(mlf, "forecast_commodity", stub)
    session = _FakeSession([
        _FakeRow("EQ_VN", "equity"), _FakeRow("COM", "agriculture"),
        _FakeRow("THIN", "metal"), _FakeRow("DEAD", "energy"),
    ])
    movers, scanned, unavailable = collect_movers(session, AlertConfig(horizon_days=30))
    assert scanned == 4 and unavailable == 2
    assert calls["EQ_VN"] == (30,)  # horizon threaded through (str-keyed lookup works)
    by_code = {m.commodity_code: m for m in movers}
    assert by_code["EQ_VN"].is_equity and not by_code["COM"].is_equity
    assert by_code["EQ_VN"].pct_move == pytest.approx(7.5)
    assert by_code["COM"].pct_move == pytest.approx(-2.0)


def test_collect_movers_db_failure_aborts_loudly(monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    import ml.forecast as mlf
    from scripts.weekly_movers_alert import collect_movers

    def stub(session, code, *, horizons):
        raise OperationalError("SELECT 1", {}, Exception("connection dropped"))

    monkeypatch.setattr(mlf, "forecast_commodity", stub)
    session = _FakeSession([_FakeRow("A", "metal"), _FakeRow("B", "metal")])
    with pytest.raises(OperationalError):  # never laundered into "unavailable"
        collect_movers(session, AlertConfig())


def test_main_exit_codes(monkeypatch, capsys) -> None:
    import ml.forecast as mlf
    import scripts.weekly_movers_alert as wm

    session = _FakeSession([_FakeRow("EQ_VN", "equity"), _FakeRow("COM", "agriculture")])
    # main() imports get_session_factory at call time — patch the source module
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: (lambda: session))

    # dry-run with data ⇒ 0
    monkeypatch.setattr(mlf, "forecast_commodity", _forecast_stub(+3.0))
    assert wm.main([]) == 0

    # --send with zero usable channels ⇒ 1 (fail closed)
    monkeypatch.setattr(wm.os, "environ", {})
    assert wm.main(["--send"]) == 1

    # systemic unavailability (>50%) ⇒ 1 even in dry-run
    monkeypatch.setattr(mlf, "forecast_commodity", _forecast_stub(0.0, available=False))
    assert wm.main([]) == 1
    out = capsys.readouterr().out
    assert "systemic" in out or "refusing" in out


# ── freshness gate (trading-day aware) ───────────────────────────────────────
def test_trading_days_weekend_boundary() -> None:
    from datetime import date

    from scripts.weekly_movers_alert import trading_days_between

    fri, mon, thu = date(2026, 7, 17), date(2026, 7, 20), date(2026, 7, 23)
    assert trading_days_between(fri, mon) == 1  # Fri→Mon = ONE trading day, not 3
    assert trading_days_between(fri, thu) == 4
    assert trading_days_between(mon, mon) == 0
    assert trading_days_between(mon, fri) == 0  # end before start


def test_apply_freshness_excludes_skewed_assets() -> None:
    from datetime import date

    from scripts.weekly_movers_alert import apply_freshness

    cfg = AlertConfig(max_asset_skew_trading_days=5)
    fresh_m = _mover("FRESH", 1.0, equity=False)
    laggard = Mover(**{**fresh_m.__dict__, "commodity_code": "LAG", "last_date": "2026-07-01"})
    fresh, stale, lag = apply_freshness([fresh_m, laggard], cfg, today=date(2026, 7, 22))
    assert [m.commodity_code for m in fresh] == ["FRESH"]
    assert [m.commodity_code for m in stale] == ["LAG"]  # 14 trading days behind ⇒ out
    assert lag == 1  # freshest is 2026-07-21 (Tue), today Wed ⇒ 1 trading day


def test_main_refuses_stale_global_data(monkeypatch, capsys) -> None:
    import ml.forecast as mlf
    import scripts.weekly_movers_alert as wm

    session = _FakeSession([_FakeRow("EQ_VN", "equity")])
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: (lambda: session))

    def stub(s, code, *, horizons):
        out = _forecast_stub(+3.0)(s, code, horizons=horizons)
        out["last_date"] = "2026-06-01"  # weeks-old data ⇒ ingest broken
        return out

    monkeypatch.setattr(mlf, "forecast_commodity", stub)
    assert wm.main([]) == 1  # red even in dry-run — never a bulletin off dead data
    assert "refusing to send" in capsys.readouterr().out


# ── idempotency / delivery log ───────────────────────────────────────────────
def _sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=create_engine("sqlite://", future=True), future=True)()


def test_period_key_stable_within_week_and_config_sensitive() -> None:
    from scripts.weekly_movers_alert import period_key

    cfg = AlertConfig()
    mon = datetime(2026, 7, 27, 2, 5, tzinfo=UTC)  # Monday 09:05 ICT
    fri = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)  # same ISO week
    next_mon = datetime(2026, 8, 3, 2, 5, tzinfo=UTC)
    assert period_key(cfg, now_utc=mon) == period_key(cfg, now_utc=fri)  # rerun = same bulletin
    assert period_key(cfg, now_utc=mon) != period_key(cfg, now_utc=next_mon)
    assert "2026-W31" in period_key(cfg, now_utc=mon)
    assert period_key(AlertConfig(horizon_days=90), now_utc=mon) != period_key(cfg, now_utc=mon)


def test_delivery_log_claim_send_rerun_and_retry() -> None:
    from scripts.weekly_movers_alert import DeliveryLog

    s = _sqlite_session()
    log = DeliveryLog(s)
    log.ensure_table()
    key, fp = "weekly-movers:2026-W31:abc", "deadbeef"

    assert log.claim(key, "telegram", fp) is True  # first claim wins
    log.mark(key, "telegram", fp, "delivered")
    assert log.claim(key, "telegram", fp) is False  # delivered ⇒ NEVER again
    assert log.status(key, "telegram", fp) == "delivered"

    assert log.claim(key, "email", fp) is True  # channels are independent records
    log.mark(key, "email", fp, "failed", "SMTPException")
    assert log.status(key, "email", fp) == "failed"
    assert log.claim(key, "email", fp) is True  # failed ⇒ per-channel retry allowed

    assert log.claim(key, "sms", fp) is True  # pending (crashed in-flight)…
    assert log.claim(key, "sms", fp) is False  # …is ambiguous ⇒ fail-closed skip
    s.close()


def test_delivery_log_insert_race_loser_does_not_send(monkeypatch) -> None:
    # Two runs pass the status() pre-check simultaneously; the PK must make the
    # loser's INSERT fail and claim() must answer False (kills the mutant that
    # drops the IntegrityError catch — without it this raises instead).
    from scripts.weekly_movers_alert import DeliveryLog

    s = _sqlite_session()
    winner, loser = DeliveryLog(s), DeliveryLog(s)
    winner.ensure_table()
    key, fp = "weekly-movers:2026-W31:race", "cafe1234"
    assert winner.claim(key, "telegram", fp) is True
    # simulate the race window: the loser's pre-check saw no row yet
    monkeypatch.setattr(loser, "status", lambda *a: None)
    assert loser.claim(key, "telegram", fp) is False  # PK collision ⇒ no send
    s.close()


def test_delivery_log_rearm_race_compare_and_set(monkeypatch) -> None:
    # Both racers READ 'failed', but only the UPDATE that actually flips the row
    # may claim — the loser's stale-read UPDATE matches 0 rows and must not send.
    from scripts.weekly_movers_alert import DeliveryLog

    s = _sqlite_session()
    log = DeliveryLog(s)
    log.ensure_table()
    key, fp = "weekly-movers:2026-W31:cas", "beef5678"
    assert log.claim(key, "telegram", fp) is True
    log.mark(key, "telegram", fp, "failed", "boom")
    racer = DeliveryLog(s)
    monkeypatch.setattr(racer, "status", lambda *a: "failed")  # stale read
    assert log.claim(key, "telegram", fp) is True  # winner re-arms (failed→pending)
    assert racer.claim(key, "telegram", fp) is False  # CAS matches 0 rows ⇒ skip
    s.close()


def test_send_marks_pending_during_flight_not_delivered_early() -> None:
    # Kills the "mark delivered before the send" mutant: AT TRANSPORT TIME the
    # record must still read 'pending' — delivered is only written afterwards.
    from scripts.weekly_movers_alert import DeliveryLog, period_key

    s = _sqlite_session()
    log = DeliveryLog(s)
    log.ensure_table()
    cfg = AlertConfig(email_enabled=False)
    key = period_key(cfg, now_utc=datetime(2026, 7, 27, 2, 0, tzinfo=UTC))
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "42"}
    seen: list[str | None] = []
    n = Notifier(cfg, env=env)
    n.telegram_post = lambda u, p: seen.append(log.status(key, "telegram", n.destination_fp("telegram")))
    delivered, _, _ = n.send("x", log=log, key=key)
    assert delivered == ["telegram"]
    assert seen == ["pending"]  # in-flight state is pending, never delivered-early
    assert log.status(key, "telegram", n.destination_fp("telegram")) == "delivered"
    s.close()


def test_period_key_sunday_ict_rolls_into_next_week() -> None:
    from scripts.weekly_movers_alert import period_key

    cfg = AlertConfig()
    sun_evening = datetime(2026, 7, 26, 16, 30, tzinfo=UTC)  # Sunday 23:30 ICT
    mon_morning = datetime(2026, 7, 27, 2, 0, tzinfo=UTC)  # Monday 09:00 ICT
    assert period_key(cfg, now_utc=sun_evening) == period_key(cfg, now_utc=mon_morning)
    assert "2026-W31" in period_key(cfg, now_utc=sun_evening)


def test_send_with_log_dedupes_and_marks_correctly() -> None:
    from scripts.weekly_movers_alert import DeliveryLog, period_key

    s = _sqlite_session()
    log = DeliveryLog(s)
    log.ensure_table()
    cfg = AlertConfig(email_enabled=False)
    key = period_key(cfg, now_utc=datetime(2026, 7, 27, 2, 0, tzinfo=UTC))
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "42"}
    calls: list[object] = []
    n = Notifier(cfg, env=env, telegram_post=lambda u, p: calls.append(p))

    d1 = n.send("bulletin", log=log, key=key)
    assert d1 == (["telegram"], [], []) and len(calls) == 1
    # rerun of the SAME period: mutant that drops dedupe would call the API again
    d2 = n.send("bulletin", log=log, key=key)
    assert d2 == ([], [], ["telegram"]) and len(calls) == 1  # exactly one message ever

    # mutant "mark delivered too early": a FAILING send must record failed, not delivered
    def boom(u: object, p: object) -> None:
        raise RuntimeError("api down")

    key2 = key + ":second"
    n_fail = Notifier(cfg, env=env, telegram_post=boom)
    assert n_fail.send("x", log=log, key=key2) == ([], ["telegram"], [])
    assert log.status(key2, "telegram", n_fail.destination_fp("telegram")) == "failed"
    # and the retry then succeeds on the same period key
    assert n.send("x", log=log, key=key2) == (["telegram"], [], [])
    assert log.status(key2, "telegram", n.destination_fp("telegram")) == "delivered"
    s.close()


# ── workflow contract (mirror of the repo's ingest-workflow pinning pattern) ──
_WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "weekly-movers.yml"


def test_weekly_movers_workflow_contract() -> None:
    wf = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)  # PyYAML may parse bare `on:` as boolean True
    assert on["schedule"] == [{"cron": "0 2 * * 1"}]  # Monday 02:00 UTC = 09:00 ICT
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True  # manual = dry-run
    assert wf.get("permissions") == {"contents": "read"}  # least privilege
    job = wf["jobs"]["alert"]
    assert job["timeout-minutes"] == 30
    steps = job["steps"]
    run_step = next(s for s in steps if "weekly_movers_alert.py" in str(s.get("run", "")))
    # failure must be RED: the notification step is never continue-on-error
    assert "continue-on-error" not in run_step and "continue-on-error" not in job
    run = run_step["run"]
    assert "--send" in run and "github.event_name" in run  # scheduled path delivers
    env = run_step.get("env") or {}
    assert "${{ secrets.DATABASE_URL }}" in env.get("DATABASE_URL", "")
    assert "TELEGRAM_BOT_TOKEN" in env and "ALERT_SMTP_HOST" in env
