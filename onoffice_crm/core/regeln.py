"""Reine Fachlogik (ohne API) – gut testbar und von späteren Modulen wiederverwendbar."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from .config import AktionsartSpec
from .repository import Aktivitaet


def _tag(dt: datetime | None) -> date | None:
    return dt.date() if dt else None


def je_adresse(aktivitaeten: Iterable[Aktivitaet]) -> dict[str, list[Aktivitaet]]:
    """Gruppiert nach Adresse, je Adresse aufsteigend nach Datum."""
    out: dict[str, list[Aktivitaet]] = defaultdict(list)
    for a in aktivitaeten:
        if a.datum is None:
            continue
        for aid in a.adress_ids:
            out[aid].append(a)
    for lst in out.values():
        lst.sort(key=lambda x: x.datum)
    return dict(out)


@dataclass
class Faelligkeit:
    adress_id: str
    basis_datum: date
    stufe: int              # 1-basiert: 1 = erster Nachfass
    intervall_tag: int      # z.B. 14 / 56 / 180
    faellig_am: date
    ueberfaellig_tage: int
    objekt_ids: list[str]


def faellige_nachfass(aktivitaeten: Iterable[Aktivitaet], basis: list[AktionsartSpec],
                      nachfass: list[AktionsartSpec], intervalle: list[int], heute: date) -> list[Faelligkeit]:
    """Intervall-Logik (MPE [14,56,180], Kaltakquise [10,30,90], später [90,180,365]).

    Basis = jüngste Basis-Aktivität je Adresse (z.B. die MPE).
    Stufe k = Anzahl Nachfass-Aktivitäten nach der Basis.
    Fällig, wenn heute >= Basis + intervalle[k]. Nach dem letzten Intervall: nicht mehr fällig.
    """
    out: list[Faelligkeit] = []
    for aid, akts in je_adresse(aktivitaeten).items():
        basis_akts = [a for a in akts if a.ist(basis)]
        if not basis_akts:
            continue
        b = basis_akts[-1]
        k = sum(1 for a in akts if a.datum > b.datum and a.ist(nachfass) and not a.ist(basis))
        if k >= len(intervalle):
            continue
        faellig = _tag(b.datum) + timedelta(days=intervalle[k])
        if heute >= faellig:
            out.append(Faelligkeit(aid, _tag(b.datum), k + 1, intervalle[k], faellig,
                                   (heute - faellig).days, b.objekt_ids))
    out.sort(key=lambda f: (-f.ueberfaellig_tage, f.adress_id))
    return out


@dataclass
class OhneAntwort:
    adress_id: str
    datum: date
    tage: int
    objekt_ids: list[str]


def ohne_antwort(aktivitaeten: Iterable[Aktivitaet], basis: list[AktionsartSpec],
                 antwort: list[AktionsartSpec], min_tage: int, max_tage: int,
                 heute: date) -> list[OhneAntwort]:
    """Jüngste Basis-Aktivität liegt min..max Tage zurück und danach keine Antwort-Aktivität."""
    out: list[OhneAntwort] = []
    for aid, akts in je_adresse(aktivitaeten).items():
        basis_akts = [a for a in akts if a.ist(basis)]
        if not basis_akts:
            continue
        b = basis_akts[-1]
        tage = (heute - _tag(b.datum)).days
        if not (min_tage <= tage <= max_tage):
            continue
        if any(a.datum > b.datum and a.ist(antwort) for a in akts):
            continue
        out.append(OhneAntwort(aid, _tag(b.datum), tage, b.objekt_ids))
    out.sort(key=lambda x: (-x.tage, x.adress_id))
    return out


@dataclass
class Anfrage:
    adress_id: str
    datum: datetime
    objekt_ids: list[str]
    agreement: bool
    agreement_datum: datetime | None
    erinnerungen: int

    @property
    def stufe(self) -> int:
        return 2 if self.agreement else 1


def anfragen_mit_status(anfragen: Iterable[Aktivitaet], agreements: Iterable[Aktivitaet],
                        erinnerungen: Iterable[Aktivitaet] = ()) -> list[Anfrage]:
    """Je Adresse die jüngste Anfrage + ob ein Agreement existiert (egal wann)
    + Anzahl Stufe-1-Erinnerungen nach der Anfrage."""
    agr = je_adresse(agreements)
    eri = je_adresse(erinnerungen)
    out: list[Anfrage] = []
    for aid, akts in je_adresse(anfragen).items():
        last = akts[-1]
        objekte = list(dict.fromkeys(o for a in akts for o in a.objekt_ids))
        agr_list = agr.get(aid, [])
        n_eri = sum(1 for e in eri.get(aid, []) if e.datum >= last.datum)
        out.append(Anfrage(aid, last.datum, objekte, bool(agr_list),
                           agr_list[-1].datum if agr_list else None, n_eri))
    out.sort(key=lambda a: a.datum, reverse=True)
    return out


def zaehle(aktivitaeten: Iterable[Aktivitaet], gruppen: dict[str, list[AktionsartSpec]]) -> dict[str, int]:
    akts = list(aktivitaeten)
    return {name: sum(1 for a in akts if a.ist(specs)) for name, specs in gruppen.items()}


def kuerzen(text: str, n: int) -> str:
    """Notiz für die Mail kürzen; HTML-Reste/Zeilenumbrüche entfernen."""
    import re
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: max(n - 1, 0)].rstrip() + "…"
