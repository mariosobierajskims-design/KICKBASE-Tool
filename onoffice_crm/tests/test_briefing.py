from modules import briefing, wochenbericht
from modules.base import render_text


def keys(abschnitte):
    return {a.key: a for a in abschnitte}


def titel(a):
    return [e.titel for e in a.eintraege]


def test_montag(make_ctx, session):
    ctx = make_ctx("2026-11-09")
    ab = keys(briefing.Briefing(ctx).erstellen())
    # Reihenfolge: Mo-Stapel dann täglich
    assert list(ab)[:2] == ["besichtigungen_rueckblick", "stufe1_offen"]
    assert titel(ab["portal_stufe2"]) == ["Bernd Becker"]
    assert sorted(titel(ab["portal_stufe1"])) == ["Anna Albers", "Dieter Dahl"]
    # Besichtigungen letzter Do (05.11.) + Sa (07.11.)
    assert sorted(titel(ab["besichtigungen_rueckblick"])) == ["Anna Albers", "Bernd Becker"]
    becker = next(e for e in ab["besichtigungen_rueckblick"].eintraege if e.titel == "Bernd Becker")
    assert any("Agreement" in z or "Finanzierung" in z or "Notiz" in z for z in becker.zeilen)
    # Stufe 1 Runde 1: >=2 Tage, ohne Agreement, jünger als Runde-2-Grenze
    assert sorted(titel(ab["stufe1_offen"])) == ["Anna Albers", "Dieter Dahl"]
    assert ab["stufe1_offen"].hinweis  # Runde nach Alter geschätzt
    # Termine heute/morgen: Eigentümertermin 201 mit Historie
    t = ab["termine_heute_morgen"].eintraege
    assert len(t) == 1 and "Eigentümertermin" in t[0].titel
    assert any("MPE" in z for z in t[0].zeilen)
    # Objekte ohne Besichtigung nächste 7 Tage: 502 (501 hat am 12.11.)
    assert titel(ab["objekte_ohne_besichtigung"]) == ["H-502 · EFH Gerresheim"]
    # ohne nächsten Schritt: 201 hat Termin, 202 Wiedervorlage; 203 nur überfällige Aufgabe
    o = ab["ohne_naechsten_schritt"].eintraege
    assert [e.titel for e in o] == ["Greta Gruber"] and o[0].tag == "Wiedervorlage überfällig"


def test_dienstag_erster_im_monat(make_ctx):
    ab = keys(briefing.Briefing(make_ctx("2026-11-03")).erstellen())
    assert titel(ab["mpe_faellig"]) == ["Eva Ebert"]           # MPE 20.10. + 14
    assert titel(ab["kaltakquise_ohne_antwort"]) == ["Hans Hoff"]
    assert sorted(titel(ab["mpe_monatscheck"])) == ["Eva Ebert", "Greta Gruber"]


def test_dienstag_kein_monatscheck(make_ctx):
    ab = keys(briefing.Briefing(make_ctx("2026-11-10")).erstellen())
    assert "mpe_monatscheck" not in ab


def test_mittwoch(make_ctx):
    ab = keys(briefing.Briefing(make_ctx("2026-11-11")).erstellen())
    akt = {e.titel: e for e in ab["objekte_aktivitaet"].eintraege}
    assert akt["W-501 · Altbauwohnung Oberkassel"].zeilen == ["Anfragen 2 · Exposés 1 · Besichtigungen 1"]  # 03.11. liegt vor dem 7-Tage-Fenster
    assert akt["H-502 · EFH Gerresheim"].zeilen == ["Anfragen 1 · Exposés 0 · Besichtigungen 0"]
    lz = ab["objekte_laufzeit"].eintraege
    assert [e.titel for e in lz] == ["W-501 · Altbauwohnung Oberkassel"] and lz[0].tag == "71 Tage"


def test_donnerstag(make_ctx):
    ab = keys(briefing.Briefing(make_ctx("2026-11-12")).erstellen())
    assert titel(ab["besichtigungen_rueckblick"]) == []   # letzter Di 10.11.: keine
    assert titel(ab["objekte_reserviert"]) == ["W-503 · Penthouse Medienhafen"]
    assert "Clara Claasen" in titel(ab["stufe1_runde2"])


def test_freitag_wochenzahlen(make_ctx):
    ab = keys(briefing.Briefing(make_ctx("2026-11-06")).erstellen())
    zahlen = {e.titel.split(":")[0]: e for e in ab["wochenzahlen"].eintraege}
    assert zahlen["Besichtigungen"].titel == "Besichtigungen: 2"
    assert zahlen["Kaltakquise"].titel == "Kaltakquise: 0"


def test_nicht_konfiguriert(make_ctx, cfg):
    cfg.data["adresse"]["merkmal_feld"] = None
    cfg.data["aktionsarten"]["mpe"] = None
    ab = keys(briefing.Briefing(make_ctx("2026-11-03")).erstellen())
    assert "Nicht konfiguriert" in ab["ohne_naechsten_schritt"].hinweis
    assert "aktionsarten.mpe" in ab["mpe_faellig"].hinweis


def test_fehler_in_abschnitt_bricht_nicht_ab(make_ctx, monkeypatch):
    def boom(b):
        raise RuntimeError("x")
    monkeypatch.setitem(briefing.ABSCHNITTE, "objekte_ohne_besichtigung", boom)
    ab = keys(briefing.Briefing(make_ctx("2026-11-09")).erstellen())
    assert "Fehler" in ab["objekte_ohne_besichtigung"].hinweis
    assert ab["portal_stufe2"].eintraege


def test_run_console_schreibt_html_und_sendet_nicht(make_ctx, capsys, monkeypatch):
    sent = []
    monkeypatch.setattr("modules.base.send_to_self", lambda *a, **k: sent.append(a))
    ctx = make_ctx("2026-11-09", console=True, dry_run=True)
    assert briefing.run(ctx) == 0
    out = capsys.readouterr().out
    assert "Briefing Montag, 09.11.2026" in out and "Bernd Becker" in out
    assert not sent


def test_run_sendet_mail_an_mich(make_ctx, monkeypatch):
    sent = []
    monkeypatch.setattr("modules.base.send_to_self", lambda s, betreff, html, text: sent.append((betreff, html)))
    assert briefing.run(make_ctx("2026-11-09", console=False, dry_run=False)) == 0
    betreff, html = sent[0]
    assert "1 Anrufe" in betreff and "<html" in html and "viewport" in html


def test_wochenbericht_vergleich(make_ctx, monkeypatch):
    z = wochenbericht.berechne(make_ctx("2026-11-06"))     # KW 45: 02.–06.11.
    werte = {zl.name: (zl.aktuell, zl.vorwoche) for zl in z.zeilen}
    assert werte["Portal-Anfragen"] == (3, 0)
    assert werte["Kaltakquise"] == (0, 1)                  # 30.10. = Fr der Vorwoche
    assert werte["Exposés"] == (1, 1)
    assert "Neue Aufträge" in z.fehlend or werte["Neue Aufträge"] == (0, 0)
    text = wochenbericht.entwurf_text(z)
    assert "KW 45" in text


def test_text_render_weitere():
    from modules.base import Abschnitt, Eintrag
    a = Abschnitt("x", "X", [Eintrag(str(i)) for i in range(5)], max_eintraege=2)
    assert "+ 3 weitere" in render_text("T", [a])


def test_keine_schreibaktionen(make_ctx, session):
    for d in ("2026-11-03", "2026-11-09", "2026-11-11", "2026-11-12", "2026-11-06"):
        briefing.Briefing(make_ctx(d)).erstellen()
    ids = {a["actionid"].rsplit(":", 1)[-1] for c in session.calls for a in c["request"]["actions"]}
    assert ids <= {"read", "get"}
