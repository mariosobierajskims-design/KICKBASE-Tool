from datetime import date, datetime

from core.config import AktionsartSpec
from core.regeln import anfragen_mit_status, faellige_nachfass, kuerzen, ohne_antwort, zaehle
from core.repository import Aktivitaet
from core.timeutil import TZ

MPE = [AktionsartSpec("MPE")]
NF = [AktionsartSpec("Nachfass")]


def akt(d, art, adr, typ=""):
    return Aktivitaet(1, datetime.fromisoformat(d).replace(tzinfo=TZ), art, typ, [str(adr)], [])


def test_faellige_nachfass_stufen():
    akts = [akt("2026-10-01", "MPE", 1),
            akt("2026-10-01", "MPE", 2), akt("2026-10-15", "Nachfass", 2),
            akt("2026-01-01", "MPE", 3), akt("2026-01-15", "Nachfass", 3), akt("2026-03-01", "Nachfass", 3),
            akt("2026-07-01", "Nachfass", 3)]
    res = {f.adress_id: f for f in faellige_nachfass(akts, MPE, NF, [14, 56, 180], date(2026, 10, 20))}
    assert res["1"].stufe == 1 and res["1"].ueberfaellig_tage == 5
    assert "2" not in res          # Stufe 2 erst an Tag 56
    assert "3" not in res          # alle Intervalle durch


def test_faellig_genau_am_tag():
    res = faellige_nachfass([akt("2026-10-01", "MPE", 1)], MPE, NF, [14], date(2026, 10, 15))
    assert res and res[0].ueberfaellig_tage == 0


def test_neue_mpe_setzt_zurueck():
    akts = [akt("2026-01-01", "MPE", 1), akt("2026-01-20", "Nachfass", 1), akt("2026-10-01", "MPE", 1)]
    res = faellige_nachfass(akts, MPE, NF, [14, 56], date(2026, 10, 16))
    assert res[0].stufe == 1


def test_ohne_antwort_fenster():
    K, ANT = [AktionsartSpec("Kaltakquise")], [AktionsartSpec("Erstgespräch")]
    akts = [akt("2026-10-01", "Kaltakquise", 1), akt("2026-10-01", "Kaltakquise", 2),
            akt("2026-10-05", "Erstgespräch", 2), akt("2026-10-18", "Kaltakquise", 3),
            akt("2026-09-01", "Kaltakquise", 4)]
    res = [r.adress_id for r in ohne_antwort(akts, K, ANT, 10, 30, date(2026, 10, 20))]
    assert res == ["1"]


def test_anfragen_status():
    anfr = [akt("2026-11-01", "Anfrage", 1), akt("2026-11-02", "Anfrage", 2)]
    agr = [akt("2026-11-03", "Agreement", 2)]
    eri = [akt("2026-11-04", "Erinnerung", 1)]
    res = {a.adress_id: a for a in anfragen_mit_status(anfr, agr, eri)}
    assert res["1"].stufe == 1 and res["1"].erinnerungen == 1
    assert res["2"].stufe == 2


def test_aktionstyp_matching_and_count():
    spec = [AktionsartSpec("Email", "Eingang")]
    akts = [akt("2026-11-01", "Email", 1, "Eingang"), akt("2026-11-01", "Email", 1, "Ausgang")]
    assert zaehle(akts, {"Mails": spec}) == {"Mails": 1}


def test_kuerzen():
    assert kuerzen("<p>Hallo\n Welt</p>", 100) == "Hallo Welt"
    assert kuerzen("x" * 50, 10) == "x" * 9 + "…"
