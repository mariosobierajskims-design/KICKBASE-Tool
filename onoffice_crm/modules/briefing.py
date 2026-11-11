"""Phase 1 – Tägliches Briefing (9:30) an mich. NUR LESEN.

Abschnitte sind registrierte Funktionen (ABSCHNITTE). Welche wann laufen, steht in
config.yaml (wochentage / taeglich). Neue Abschnitte: Funktion schreiben, mit
@abschnitt("key") registrieren, Key in config.yaml eintragen.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Callable

from core.config import ConfigError
from core.logger import get_logger
from core.onoffice_client import OnOfficeAuthError
from core.regeln import Anfrage, anfragen_mit_status, faellige_nachfass, kuerzen, ohne_antwort
from core.repository import Adresse, Aktivitaet, Termin
from core.timeutil import (end_of_day, fmt_de, ist_erster_wochentag_im_monat, letzter_wochentag,
                           parse_dt, start_of_day, vorheriger_werktag, wochentag_key)

from .base import Abschnitt, Eintrag, RunContext, ausgeben, render_html, render_text

log = get_logger("briefing")

WT_LANG = {"mo": "Montag", "di": "Dienstag", "mi": "Mittwoch", "do": "Donnerstag",
           "fr": "Freitag", "sa": "Samstag", "so": "Sonntag"}
WT_KURZ = {k: v[:2] for k, v in WT_LANG.items()}

ABSCHNITTE: dict[str, Callable[["Briefing"], list[Abschnitt]]] = {}


def abschnitt(key: str):
    def deco(fn):
        ABSCHNITTE[key] = fn
        return fn
    return deco


def nicht_konfiguriert(key: str, titel: str, was: str) -> list[Abschnitt]:
    return [Abschnitt(key, titel, hinweis=f"Nicht konfiguriert: {was} (config.yaml)")]


class Briefing:
    """Hält Kontext + Caches für einen Lauf (Termine/Agreements werden mehrfach gebraucht)."""

    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.repo = ctx.repo
        self.heute = ctx.heute
        self.max = int(self.cfg.get("briefing.max_eintraege", 15))
        self.notiz_len = int(self.cfg.get("briefing.notiz_max_zeichen", 160))
        self._termine: dict[tuple[date, date], list[Termin]] = {}
        self._vermarktung = None

    # --- gemeinsame Daten ---------------------------------------------
    def termine(self, von: date, bis: date) -> list[Termin]:
        if (von, bis) not in self._termine:
            self._termine[(von, bis)] = self.repo.termine(von, bis)
        return self._termine[(von, bis)]

    def besichtigungen(self, von: date, bis: date) -> list[Termin]:
        typen = self.cfg.get("termine.besichtigung_typen") or []
        return [t for t in self.termine(von, bis) if t.hat_typ(typen)]

    def objekte_in_vermarktung(self):
        if self._vermarktung is None:
            self._vermarktung = self.repo.objekte_gefiltert("vermarktung_filter")
        return self._vermarktung

    def agreements(self, adress_ids: list[str]) -> list[Aktivitaet]:
        specs = self.cfg.aktionsart("agreement_bestaetigt")
        if not specs or not adress_ids:
            return []
        tage = int(self.cfg.get("anfragen.agreement_lookback_tage", 365))
        return self.repo.aktivitaeten(seit=start_of_day(self.heute - timedelta(days=tage)),
                                      arten=specs, adress_ids=adress_ids)

    # --- Formatierung -------------------------------------------------
    def kontakt(self, a: Adresse | None, fallback_id: str) -> tuple[str, str]:
        if a is None:
            return f"Adresse {fallback_id}", ""
        return a.name, (f"Tel. {a.telefon}" if a.telefon else "Tel. –")

    def objekt_text(self, ids: list[str]) -> str:
        if not ids:
            return ""
        objs = self.repo.objekte(ids)
        return ", ".join(objs[i].anzeige if i in objs else f"Objekt {i}" for i in ids[:3])

    def abschnitt(self, key: str, titel: str, eintraege: list[Eintrag], **kw) -> Abschnitt:
        return Abschnitt(key, titel, eintraege, max_eintraege=self.max, **kw)

    # --- Lauf -----------------------------------------------------------
    def keys_fuer_heute(self) -> list[str]:
        wt = wochentag_key(self.heute)
        stapel = list((self.cfg.get("wochentage") or {}).get(wt) or [])
        taeglich = list(self.cfg.get("taeglich") or [])
        keys = taeglich + stapel if self.cfg.get("briefing.taeglich_zuerst") else stapel + taeglich
        return list(dict.fromkeys(keys))

    def erstellen(self) -> list[Abschnitt]:
        out: list[Abschnitt] = []
        for key in self.keys_fuer_heute():
            fn = ABSCHNITTE.get(key)
            if fn is None:
                out.append(Abschnitt(key, key, hinweis=f"Unbekannter Abschnitt '{key}' in config.yaml"))
                continue
            try:
                out.extend(fn(self))
            except OnOfficeAuthError:
                raise
            except (ConfigError, Exception) as exc:  # ein kaputter Abschnitt soll das Briefing nicht verhindern
                log.error("Abschnitt %s fehlgeschlagen: %s: %s", key, type(exc).__name__, exc)
                out.append(Abschnitt(key, key, hinweis=f"Fehler beim Erstellen ({type(exc).__name__}) – siehe Log"))
        return out


# =====================================================================
# Täglich
# =====================================================================
@abschnitt("portal_anfragen_neu")
def portal_anfragen_neu(b: Briefing) -> list[Abschnitt]:
    specs = b.cfg.aktionsart("portal_anfrage")
    if not specs:
        return nicht_konfiguriert("portal_anfragen_neu", "Neue Portal-Anfragen", "aktionsarten.portal_anfrage")
    seit = start_of_day(vorheriger_werktag(b.heute))
    neu = b.repo.aktivitaeten(seit=seit, arten=specs)
    agr_specs = b.cfg.aktionsart("agreement_bestaetigt")
    agr_neu = b.repo.aktivitaeten(seit=seit, arten=agr_specs) if agr_specs else []
    ids = list(dict.fromkeys([i for a in neu + agr_neu for i in a.adress_ids]))
    anfragen = {a.adress_id: a for a in anfragen_mit_status(neu, b.agreements(ids))}
    # Agreement neu bestätigt zu einer älteren Anfrage -> ebenfalls Stufe 2
    for a in agr_neu:
        for aid in a.adress_ids:
            if aid not in anfragen:
                anfragen[aid] = Anfrage(aid, a.datum, a.objekt_ids, True, a.datum, 0)
    adressen = b.repo.adressen(anfragen.keys())
    stufe2, stufe1 = [], []
    for aid, anf in sorted(anfragen.items(), key=lambda kv: kv[1].datum, reverse=True):
        name, tel = b.kontakt(adressen.get(aid), aid)
        zeilen = [z for z in (tel, b.objekt_text(anf.objekt_ids), f"Eingang {fmt_de(anf.datum, True)}") if z]
        if anf.agreement:
            stufe2.append(Eintrag(name, zeilen, tag="heute anrufen", wichtig=True))
        else:
            stufe1.append(Eintrag(name, zeilen, tag="Stufe 1"))
    seit_txt = fmt_de(seit.date())
    return [
        b.abschnitt("portal_stufe2", "Stufe 2 – Agreement bestätigt → heute anrufen", stufe2,
                    leer_text=f"Keine neuen Agreements seit {seit_txt}."),
        b.abschnitt("portal_stufe1", f"Neue Portal-Anfragen Stufe 1 (seit {seit_txt})", stufe1,
                    leer_text="Keine neuen Anfragen ohne Agreement."),
    ]


@abschnitt("termine_heute_morgen")
def termine_heute_morgen(b: Briefing) -> list[Abschnitt]:
    morgen = b.heute + timedelta(days=1)
    termine = b.termine(b.heute, morgen)
    kontakt_ids = list(dict.fromkeys(k for t in termine for k in t.kontakt_ids))
    adressen = b.repo.adressen(kontakt_ids) if kontakt_ids else {}
    n = int(b.cfg.get("briefing.letzte_aktivitaeten", 3))
    historie = b.repo.letzte_aktivitaeten(kontakt_ids, n) if kontakt_ids else {}
    eintraege = []
    for t in termine:
        tag_txt = "Heute" if t.start and t.start.date() == b.heute else "Morgen"
        zeit = t.start.strftime("%H:%M") if t.start else "–"
        zeilen = []
        obj = b.objekt_text([t.objekt_id] if t.objekt_id else [])
        if obj:
            zeilen.append(obj)
        for k in t.kontakt_ids:
            name, tel = b.kontakt(adressen.get(k), k)
            zeilen.append(f"👤 {name} · {tel}")
            for akt in historie.get(k, []):
                notiz = kuerzen(akt.bemerkung, 80)
                zeilen.append(f"   {fmt_de(akt.datum)} {akt.aktionsart}{': ' + notiz if notiz else ''}")
        titel = f"{tag_txt} {zeit} · {t.typ_label or t.typ_value or 'Termin'}"
        if t.betreff:
            titel += f" · {kuerzen(t.betreff, 60)}"
        eintraege.append(Eintrag(titel, zeilen))
    return [Abschnitt("termine_heute_morgen", "Termine heute & morgen", eintraege,
                      leer_text="Keine Termine heute/morgen.")]


@abschnitt("objekte_ohne_besichtigung")
def objekte_ohne_besichtigung(b: Briefing) -> list[Abschnitt]:
    tage = int(b.cfg.get("termine.vorschau_tage_besichtigung", 7))
    bis = b.heute + timedelta(days=tage)
    geplant = {t.objekt_id for t in b.besichtigungen(b.heute, bis) if t.objekt_id}
    eintraege = [Eintrag(o.anzeige) for o in b.objekte_in_vermarktung() if o.id not in geplant]
    return [b.abschnitt("objekte_ohne_besichtigung", f"Objekte ohne Besichtigung (nächste {tage} Tage)",
                        eintraege, leer_text="Alle Objekte in Vermarktung haben Besichtigungen geplant.")]


@abschnitt("ohne_naechsten_schritt")
def ohne_naechsten_schritt(b: Briefing) -> list[Abschnitt]:
    titel = "Kontakte ohne nächsten Schritt"
    keys = b.cfg.get("ohne_naechsten_schritt.merkmale") or []
    kandidaten: dict[str, Adresse] = {}
    for key in keys:
        res = b.repo.adressen_mit_merkmal(key)
        if res is None:
            return nicht_konfiguriert("ohne_naechsten_schritt", titel,
                                      f"adresse.merkmal_feld / merkmale.{key}")
        for a in res:
            kandidaten[a.id] = a
    if not kandidaten:
        return [Abschnitt("ohne_naechsten_schritt", titel, leer_text="Keine Kontakte mit diesen Merkmalen.")]
    horizont = int(b.cfg.get("termine.vorschau_tage_naechster_schritt", 90))
    mit_termin = {k for t in b.termine(b.heute, b.heute + timedelta(days=horizont)) for k in t.kontakt_ids}
    rest = [i for i in kandidaten if i not in mit_termin]
    aufgaben = b.repo.offene_aufgaben_je_adresse(rest)
    eintraege = []
    for aid in rest:
        offen = aufgaben.get(aid, [])
        kuenftig = [t for t in offen if t.deadline is None or t.deadline.date() >= b.heute]
        if kuenftig:
            continue
        name, tel = b.kontakt(kandidaten[aid], aid)
        tag = "Wiedervorlage überfällig" if offen else ""
        eintraege.append(Eintrag(name, [tel], tag=tag))
    return [b.abschnitt("ohne_naechsten_schritt", f"{titel} (MPE/Eigentümer-Leads)", eintraege,
                        leer_text="Alle haben eine Wiedervorlage oder einen Termin.")]


# =====================================================================
# Wochentags-Stapel
# =====================================================================
@abschnitt("besichtigungen_rueckblick")
def besichtigungen_rueckblick(b: Briefing) -> list[Abschnitt]:
    wt = wochentag_key(b.heute)
    tage_keys = (b.cfg.get("besichtigung_rueckblick") or {}).get(wt) or []
    if not tage_keys:
        return []
    tage = sorted(letzter_wochentag(b.heute, k) for k in tage_keys)
    termine = [t for d in tage for t in b.besichtigungen(d, d)]
    ids = list(dict.fromkeys(k for t in termine for k in t.kontakt_ids))
    adressen = b.repo.adressen(ids) if ids else {}
    historie = b.repo.letzte_aktivitaeten(ids, 3) if ids else {}
    eintraege = []
    for t in termine:
        obj = b.objekt_text([t.objekt_id] if t.objekt_id else [])
        wann = f"{WT_KURZ[wochentag_key(t.start.date())]} {fmt_de(t.start, True)}" if t.start else ""
        for k in t.kontakt_ids or [""]:
            if not k:
                eintraege.append(Eintrag(f"(ohne Kontakt) {obj}", [wann]))
                continue
            name, tel = b.kontakt(adressen.get(k), k)
            notiz = next((a.bemerkung for a in historie.get(k, []) if a.bemerkung.strip()), "")
            zeilen = [z for z in (f"{wann} · {obj}" if obj else wann, tel,
                                  f"Letzte Notiz: {kuerzen(notiz, b.notiz_len)}" if notiz else "Keine Notiz") if z]
            eintraege.append(Eintrag(name, zeilen, tag="nachfassen"))
    tage_txt = " + ".join(f"{WT_KURZ[wochentag_key(d)]} {fmt_de(d)[:6]}" for d in tage)
    return [b.abschnitt("besichtigungen_rueckblick", f"Besichtigungen nachfassen ({tage_txt})", eintraege,
                        leer_text="Keine Besichtigungen an diesen Tagen.")]


def _stufe1(b: Briefing, runde: int) -> list[Abschnitt]:
    key = "stufe1_offen" if runde == 1 else "stufe1_runde2"
    titel = f"Stufe-1-Anfragen ohne Agreement – Runde {runde}"
    specs = b.cfg.aktionsart("portal_anfrage")
    if not specs:
        return nicht_konfiguriert(key, titel, "aktionsarten.portal_anfrage")
    ab = int(b.cfg.intervall("stufe1_erinnerung_ab_tagen", 2))
    maxr = int(b.cfg.intervall("stufe1_max", 2))
    lookback = int(b.cfg.get("anfragen.stufe1_lookback_tage", 30))
    anfr = b.repo.aktivitaeten(seit=start_of_day(b.heute - timedelta(days=lookback)),
                               bis=end_of_day(b.heute - timedelta(days=ab)), arten=specs)
    ids = list(dict.fromkeys(i for a in anfr for i in a.adress_ids))
    eri_specs = b.cfg.aktionsart("stufe1_erinnerung")
    erinnerungen = (b.repo.aktivitaeten(seit=start_of_day(b.heute - timedelta(days=lookback)),
                                        arten=eri_specs, adress_ids=ids) if eri_specs and ids else [])
    status = [a for a in anfragen_mit_status(anfr, b.agreements(ids), erinnerungen) if not a.agreement]
    hinweis = None
    if eri_specs:
        auswahl = [a for a in status if a.erinnerungen == runde - 1 and a.erinnerungen < maxr]
    else:
        hinweis = "Runde nach Alter geschätzt (aktionsarten.stufe1_erinnerung nicht gesetzt)"
        grenze = ab + 3
        auswahl = [a for a in status
                   if ((b.heute - a.datum.date()).days < grenze) == (runde == 1)]
    adressen = b.repo.adressen([a.adress_id for a in auswahl]) if auswahl else {}
    eintraege = []
    for a in auswahl:
        name, tel = b.kontakt(adressen.get(a.adress_id), a.adress_id)
        alter = (b.heute - a.datum.date()).days
        eintraege.append(Eintrag(name, [z for z in (tel, b.objekt_text(a.objekt_ids),
                                                    f"Anfrage {fmt_de(a.datum)} ({alter} Tage)") if z],
                                 tag=f"Erinnerung {runde}/{maxr}"))
    return [b.abschnitt(key, titel, eintraege, hinweis=hinweis, leer_text="Keine offenen Stufe-1-Anfragen.")]


@abschnitt("stufe1_offen")
def stufe1_offen(b: Briefing) -> list[Abschnitt]:
    return _stufe1(b, 1)


@abschnitt("stufe1_runde2")
def stufe1_runde2(b: Briefing) -> list[Abschnitt]:
    return _stufe1(b, 2)


@abschnitt("mpe_faellig")
def mpe_faellig(b: Briefing) -> list[Abschnitt]:
    titel = "MPE-Nachfass fällig"
    mpe, nachfass = b.cfg.aktionsart("mpe"), b.cfg.aktionsart("nachfass")
    if not mpe:
        return nicht_konfiguriert("mpe_faellig", titel, "aktionsarten.mpe")
    intervalle = list(b.cfg.intervall("mpe", [14, 56, 180]))
    seit = start_of_day(b.heute - timedelta(days=max(intervalle) + 60))
    akts = b.repo.aktivitaeten(seit=seit, arten=mpe + nachfass)
    faellig = faellige_nachfass(akts, mpe, nachfass, intervalle, b.heute)
    adressen = b.repo.adressen([f.adress_id for f in faellig]) if faellig else {}
    eintraege = []
    for f in faellig:
        name, tel = b.kontakt(adressen.get(f.adress_id), f.adress_id)
        ueber = f" · seit {f.ueberfaellig_tage} T fällig" if f.ueberfaellig_tage else " · heute fällig"
        eintraege.append(Eintrag(name, [z for z in (tel, b.objekt_text(f.objekt_ids),
                                                    f"MPE {fmt_de(f.basis_datum)}{ueber}") if z],
                                 tag=f"Tag {f.intervall_tag}", wichtig=f.ueberfaellig_tage > 7))
    return [b.abschnitt("mpe_faellig", f"{titel} (Intervalle {'/'.join(map(str, intervalle))} Tage)",
                        eintraege, leer_text="Keine MPE-Nachfasse fällig.")]


@abschnitt("kaltakquise_ohne_antwort")
def kaltakquise_ohne_antwort(b: Briefing) -> list[Abschnitt]:
    titel = "Kaltakquise ohne Antwort"
    kalt = b.cfg.aktionsart("kaltakquise")
    if not kalt:
        return nicht_konfiguriert("kaltakquise_ohne_antwort", titel, "aktionsarten.kaltakquise")
    intervalle = list(b.cfg.intervall("kaltakquise", [10, 30, 90]))
    lo, hi = intervalle[0], intervalle[1] if len(intervalle) > 1 else intervalle[0]
    antwort = b.cfg.aktionsarten(list(b.cfg.get("antwort_aktionsarten") or []))
    akts = b.repo.aktivitaeten(seit=start_of_day(b.heute - timedelta(days=hi + 1)), arten=kalt + antwort)
    treffer = ohne_antwort(akts, kalt, antwort, lo, hi, b.heute)
    adressen = b.repo.adressen([t.adress_id for t in treffer]) if treffer else {}
    eintraege = []
    for t in treffer:
        name, tel = b.kontakt(adressen.get(t.adress_id), t.adress_id)
        eintraege.append(Eintrag(name, [tel, f"Kaltakquise {fmt_de(t.datum)}"], tag=f"{t.tage} Tage"))
    return [b.abschnitt("kaltakquise_ohne_antwort", f"{titel} ({lo}–{hi} Tage)", eintraege,
                        leer_text="Keine offenen Kaltakquisen in diesem Zeitfenster.")]


@abschnitt("mpe_monatscheck")
def mpe_monatscheck(b: Briefing) -> list[Abschnitt]:
    if not ist_erster_wochentag_im_monat(b.heute):
        return []
    tage = int(b.cfg.intervall("mpe_monatscheck_tage", 56))
    titel = f"Monatscheck: MPE-Kontakte ≥ {tage} Tage ohne Kontakt"
    res = b.repo.adressen_mit_merkmal("mpe_kontakt", letzter_kontakt_vor=end_of_day(b.heute - timedelta(days=tage)))
    if res is None:
        return nicht_konfiguriert("mpe_monatscheck", titel, "adresse.merkmal_feld / merkmale.mpe_kontakt")
    feld = b.cfg.get("adresse.letzter_kontakt_feld")
    eintraege = []
    for a in res:
        name, tel = b.kontakt(a, a.id)
        lk = parse_dt(a.roh.get(feld)) if feld else None
        eintraege.append(Eintrag(name, [tel, f"Letzter Kontakt {fmt_de(lk)}"]))
    return [b.abschnitt("mpe_monatscheck", titel, eintraege, leer_text="Alle MPE-Kontakte aktuell.")]


@abschnitt("objekte_aktivitaet")
def objekte_aktivitaet(b: Briefing) -> list[Abschnitt]:
    gruppen = {"Anfragen": b.cfg.aktionsart("portal_anfrage"),
               "Exposés": b.cfg.aktionsart("expose_versendet"),
               "Besichtigungen": b.cfg.aktionsart("besichtigung")}
    alle = [s for v in gruppen.values() for s in v]
    objekte = b.objekte_in_vermarktung()
    akts = b.repo.aktivitaeten(seit=start_of_day(b.heute - timedelta(days=7)), arten=alle) if alle else []
    zaehler: dict[str, Counter] = defaultdict(Counter)
    for a in akts:
        for oid in a.objekt_ids:
            for name, specs in gruppen.items():
                if a.ist(specs):
                    zaehler[oid][name] += 1
    eintraege = []
    for o in sorted(objekte, key=lambda o: sum(zaehler[o.id].values())):
        z = zaehler[o.id]
        zeile = " · ".join(f"{n} {z[n]}" for n in gruppen if gruppen[n])
        eintraege.append(Eintrag(o.anzeige, [zeile], wichtig=sum(z.values()) == 0,
                                 tag="keine Aktivität" if not sum(z.values()) else ""))
    fehlend = [n for n, v in gruppen.items() if not v]
    return [Abschnitt("objekte_aktivitaet", "Objekte in Vermarktung – letzte 7 Tage", eintraege,
                      hinweis=f"Nicht konfiguriert: {', '.join(fehlend)}" if fehlend else None,
                      leer_text="Keine Objekte in Vermarktung.")]


@abschnitt("objekte_laufzeit")
def objekte_laufzeit(b: Briefing) -> list[Abschnitt]:
    grenze = int(b.cfg.intervall("objekt_laufzeit_warnung", 42))
    titel = f"Objekte ≥ {grenze} Tage in Vermarktung"
    feld = b.cfg.get("objekte.vermarktungsbeginn_feld")
    if not feld:
        return nicht_konfiguriert("objekte_laufzeit", titel, "objekte.vermarktungsbeginn_feld")
    eintraege = []
    for o in b.objekte_in_vermarktung():
        start = parse_dt(o.roh.get(feld))
        if not start:
            continue
        tage = (b.heute - start.date()).days
        if tage >= grenze:
            eintraege.append((tage, Eintrag(o.anzeige, [f"seit {fmt_de(start)}"], tag=f"{tage} Tage",
                                            wichtig=tage >= 2 * grenze)))
    eintraege.sort(key=lambda x: -x[0])
    return [b.abschnitt("objekte_laufzeit", titel, [e for _, e in eintraege],
                        leer_text="Kein Objekt über der Laufzeitgrenze.")]


@abschnitt("objekte_reserviert")
def objekte_reserviert(b: Briefing) -> list[Abschnitt]:
    zusatz = list(b.cfg.get("objekte.reserviert_zusatzfelder") or [])
    objs = b.repo.objekte_gefiltert("reserviert_filter", extra_felder=zusatz)
    eintraege = [Eintrag(o.anzeige, [f"{f}: {o.roh.get(f) or '–'}" for f in zusatz]) for o in objs]
    return [Abschnitt("objekte_reserviert", "Reservierte Objekte (Kaufprozess)", eintraege,
                      leer_text="Keine reservierten Objekte.")]


@abschnitt("wochenzahlen")
def wochenzahlen(b: Briefing) -> list[Abschnitt]:
    from .wochenbericht import berechne
    zahlen = berechne(b.ctx)
    eintraege = [Eintrag(f"{z.name}: {z.aktuell}", [f"Vorwoche {z.vorwoche} ({z.diff_text})"]) for z in zahlen.zeilen]
    hinweis = f"Nicht konfiguriert: {', '.join(zahlen.fehlend)}" if zahlen.fehlend else None
    return [Abschnitt("wochenzahlen", f"Wochenzahlen KW {zahlen.kw} (Vorschau)", eintraege, hinweis=hinweis)]


# =====================================================================
def run(ctx: RunContext) -> int:
    b = Briefing(ctx)
    abschnitte = b.erstellen()
    wt = wochentag_key(ctx.heute)
    titel = f"Briefing {WT_LANG[wt]}, {fmt_de(ctx.heute)}"
    anrufe = next((a.anzahl for a in abschnitte if a.key == "portal_stufe2"), 0)
    termine = next((a.anzahl for a in abschnitte if a.key == "termine_heute_morgen"), 0)
    betreff = f"{titel} – {anrufe} Anrufe, {termine} Termine"
    fuss = f"Erstellt {ctx.jetzt.strftime('%d.%m.%Y %H:%M')} · nur lesend · {ctx.repo.client.request_count} API-Requests"
    html = render_html("briefing.html", titel=titel, abschnitte=abschnitte, fuss=fuss)
    text = render_text(titel, abschnitte, fuss)
    ausgeben(ctx, "briefing", betreff, html, text)
    log.info("Briefing fertig: %d Abschnitte, %d API-Requests", len(abschnitte), ctx.repo.client.request_count)
    return 0
