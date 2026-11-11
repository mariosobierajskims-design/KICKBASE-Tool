import logging
from datetime import datetime, timedelta

from core.config import AppConfig, Settings
from core.logger import RedactingFilter
from core.mailer import build_message, send_to_self
from core.safety import KontaktStatus, VersandGuard
from core.timeutil import TZ, letzter_wochentag, parse_dt, vorheriger_werktag
from datetime import date


def test_redaction():
    f = RedactingFilter(["supersecret"])
    rec = logging.LogRecord("crm", logging.INFO, "", 0, "key %s mail a.b@c.de tel +49 211 1234567", ("supersecret",), None)
    f.filter(rec)
    assert rec.msg == "key *** mail <email> tel <tel>"


def test_settings_repr_hides_secrets():
    s = Settings(onoffice_token="tok123", onoffice_secret="sec456", smtp_password="pw789")
    r = repr(s)
    assert "tok123" not in r and "sec456" not in r and "pw789" not in r


def test_settings_defaults_safe(monkeypatch, tmp_path):
    for k in ("DRY_RUN", "AUTOMATION_ENABLED", "TESTMODE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(tmp_path / "nonexistent.env")
    assert s.dry_run is True and s.automation_enabled is False and s.testmode is True


def test_aktionsart_formen():
    c = AppConfig({"aktionsarten": {"a": "X", "b": {"aktionsart": "Email", "aktionstyp": "Eingang"},
                                    "c": None, "d": ["X", {"aktionsart": "Y"}]}})
    assert c.aktionsart("a")[0].aktionsart == "X"
    assert c.aktionsart("b")[0].aktionstyp == "Eingang"
    assert c.aktionsart("c") == [] and c.aktionsart("fehlt") == []
    assert len(c.aktionsart("d")) == 2


def test_timeutil():
    assert letzter_wochentag(date(2026, 11, 9), "do") == date(2026, 11, 5)
    assert letzter_wochentag(date(2026, 11, 12), "do") == date(2026, 11, 5)
    assert vorheriger_werktag(date(2026, 11, 9)) == date(2026, 11, 6)
    assert parse_dt("2026-11-05T16:00:00+00:00").hour == 17
    assert parse_dt("2026-11-05 16:00:00").hour == 16
    assert parse_dt("") is None


def test_mailer_nur_an_mich():
    s = Settings(smtp_host="h", mail_from="ich@example.org", mail_to="ich@example.org", smtp_security="none")
    sent = []

    class FakeSMTP:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg, to_addrs):
            sent.append((msg, to_addrs))
    send_to_self(s, "Betreff", "<p>x</p>", "x", smtp_factory=FakeSMTP)
    assert sent[0][1] == ["ich@example.org"]
    assert build_message(s, "B", "<p>x</p>", "x").get_content_type() == "multipart/alternative"


def test_versand_guard():
    cfg = AppConfig.load()
    now = datetime(2026, 11, 9, 10, tzinfo=TZ)
    k = KontaktStatus("1", "kunde@example.org", hat_agreement=False)
    aus = VersandGuard(Settings(), cfg).pruefe(k, "expose", now)
    assert not aus.erlaubt and any("Kill-Switch" in g for g in aus.gruende)
    assert any("Agreement" in g for g in aus.gruende)
    an = Settings(automation_enabled=True, testmode=True, test_whitelist=("kunde@example.org",))
    k2 = KontaktStatus("1", "kunde@example.org", hat_agreement=True, letzte_automail=now - timedelta(days=4))
    assert VersandGuard(an, cfg).pruefe(k2, "expose", now).erlaubt
    k3 = KontaktStatus("1", "kunde@example.org", merkmale={"keine_automatik"}, hat_agreement=True,
                       letzte_automail=now - timedelta(days=1))
    e = VersandGuard(an, cfg).pruefe(k3, "erinnerung", now)
    assert not e.erlaubt and len(e.gruende) == 2
    k4 = KontaktStatus("1", "fremd@example.org", hat_agreement=True)
    assert not VersandGuard(an, cfg).pruefe(k4, "erinnerung", now).erlaubt


def test_konfig_pruefen(make_ctx, capsys):
    from modules import konfig_pruefen
    rc = konfig_pruefen.run(make_ctx("2026-11-09"))
    out = capsys.readouterr().out
    assert "✓  mpe: MPE" in out
    assert "✗  erstgespraech" not in out
    assert "Merkmal_test" in out and "vermarktungsstart" in out
    assert rc == 1   # Platzhalter wie 'Absage später' existieren im Fake-System nicht
