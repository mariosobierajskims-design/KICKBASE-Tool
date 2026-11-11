"""Fachliche Lesezugriffe auf onOffice (nur lesen).

Kapselt Feldnamen/Parameter lt. API-Doku, damit Module nur mit einfachen
Datenklassen arbeiten. Alles, was systemspezifisch ist (Aktionsarten, Merkmal-Feld,
Objekt-Filter) kommt aus config.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .config import AktionsartSpec, AppConfig
from .logger import get_logger
from .onoffice_client import ACTION_GET, ACTION_READ, Action, OnOfficeClient, Record
from .timeutil import fmt_api, parse_dt

log = get_logger("repo")

AGENTSLOG_FELDER = ["Datum", "Aktionsart", "Aktionstyp", "Adress_nr", "Objekt_nr", "Bemerkung"]
TERMIN_FELDER = ["id", "subject", "type", "status", "date", "contacts", "estate", "location"]
AUFGABE_FELDER = ["Betreff", "Deadline", "Status", "erledigt", "Art"]
MULTI_ACTION_CHUNK = 20


def _ids(value: Any) -> list[str]:
    """Normalisiert ID-Angaben (Liste, Zahl, '12,13', '|12|13|') zu ['12','13']."""
    if value in (None, "", [], 0, "0"):
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            out.extend(_ids(v))
        return out
    if isinstance(value, dict):
        return _ids(value.get("id"))
    s = str(value).replace("|", ",")
    return [p.strip() for p in s.split(",") if p.strip() and p.strip() != "0"]


@dataclass
class Aktivitaet:
    id: Any
    datum: datetime | None
    aktionsart: str
    aktionstyp: str
    adress_ids: list[str]
    objekt_ids: list[str]
    bemerkung: str = ""

    def ist(self, specs: Iterable[AktionsartSpec]) -> bool:
        return any(s.matches(self.aktionsart, self.aktionstyp) for s in specs)


@dataclass
class Adresse:
    id: str
    name: str
    telefon: str
    roh: dict[str, Any] = field(default_factory=dict)


@dataclass
class Objekt:
    id: str
    titel: str
    nummer: str
    roh: dict[str, Any] = field(default_factory=dict)

    @property
    def anzeige(self) -> str:
        return f"{self.nummer} · {self.titel}" if self.nummer else (self.titel or f"Objekt {self.id}")


@dataclass
class Termin:
    id: str
    betreff: str
    typ_value: str
    typ_label: str
    status: str
    start: datetime | None
    ende: datetime | None
    kontakt_ids: list[str]
    objekt_id: str | None
    ort: str = ""

    def hat_typ(self, typen: Iterable[str]) -> bool:
        t = {x.strip().lower() for x in typen}
        return self.typ_value.lower() in t or self.typ_label.lower() in t


@dataclass
class Aufgabe:
    id: str
    betreff: str
    deadline: datetime | None
    status: str
    erledigt: bool


class Repository:
    def __init__(self, client: OnOfficeClient, cfg: AppConfig):
        self.client = client
        self.cfg = cfg
        self._adress_cache: dict[str, Adresse] = {}
        self._objekt_cache: dict[str, Objekt] = {}

    # --- Maklerbuch / Aktivitäten --------------------------------------
    @staticmethod
    def _to_aktivitaet(r: Record) -> Aktivitaet:
        return Aktivitaet(
            id=r.id,
            datum=parse_dt(r.get("Datum")),
            aktionsart=str(r.get("Aktionsart") or ""),
            aktionstyp=str(r.get("Aktionstyp") or ""),
            adress_ids=_ids(r.get("Adress_nr")),
            objekt_ids=_ids(r.get("Objekt_nr")),
            bemerkung=str(r.get("Bemerkung") or ""),
        )

    def aktivitaeten(self, seit: datetime | None = None, bis: datetime | None = None,
                     arten: list[AktionsartSpec] | None = None,
                     adress_ids: list[str] | None = None,
                     objekt_ids: list[str] | None = None) -> list[Aktivitaet]:
        """Maklerbuch lesen. Datum/Aktionsart werden serverseitig gefiltert,
        Aktionstyp clientseitig (Doku nennt nur Aktionsart-Filter als Beispiel)."""
        if arten is not None and not arten:
            return []
        params: dict[str, Any] = {"data": AGENTSLOG_FELDER, "sortby": "Datum", "sortorder": "DESC"}
        flt: dict[str, Any] = {}
        if seit and bis:
            flt["Datum"] = [{"op": "between", "val": [fmt_api(seit), fmt_api(bis)]}]
        elif seit:
            flt["Datum"] = [{"op": ">=", "val": fmt_api(seit)}]
        elif bis:
            flt["Datum"] = [{"op": "<=", "val": fmt_api(bis)}]
        if arten:
            namen = sorted({s.aktionsart for s in arten})
            flt["Aktionsart"] = [{"op": "in", "val": namen}]
        if flt:
            params["filter"] = flt
        if adress_ids:
            params["addressid"] = [int(i) for i in adress_ids]
        if objekt_ids:
            params["estateid"] = [int(i) for i in objekt_ids]
        recs = self.client.read_all("agentslog", params)
        out = [self._to_aktivitaet(r) for r in recs]
        if arten:
            out = [a for a in out if a.ist(arten)]
        log.info("agentslog: %d Einträge", len(out))
        return out

    def letzte_aktivitaeten(self, adress_ids: list[str], n: int = 3) -> dict[str, list[Aktivitaet]]:
        """Letzte n Aktivitäten je Adresse (Multi-Action-Requests, je Adresse eine Action)."""
        out: dict[str, list[Aktivitaet]] = {}
        ids = list(dict.fromkeys(adress_ids))
        for i in range(0, len(ids), MULTI_ACTION_CHUNK):
            chunk = ids[i:i + MULTI_ACTION_CHUNK]
            actions = [Action(ACTION_READ, "agentslog",
                              {"data": AGENTSLOG_FELDER, "addressid": [int(a)], "listlimit": n,
                               "sortby": "Datum", "sortorder": "DESC"}, identifier=a) for a in chunk]
            results = self.client.execute(actions)
            for aid, res in zip(chunk, results):
                akts = [self._to_aktivitaet(r) for r in self.client.records_of(res)]
                akts.sort(key=lambda a: a.datum.timestamp() if a.datum else 0.0, reverse=True)
                out[aid] = akts[:n]
        return out

    # --- Adressen ------------------------------------------------------
    def _to_adresse(self, r: Record) -> Adresse:
        name = " ".join(str(r.get(f) or "").strip() for f in self.cfg.get("adresse.name_felder", ["Vorname", "Name"]))
        tel = ""
        for f in self.cfg.get("adresse.telefon_felder", ["defaultphone"]):
            val = r.get(f)
            if val:
                tel = str(val)
                break
        if not tel:  # Kontaktfelder kommen lt. Doku als phone__<id>, mobile__<id>
            for k, v in r.elements.items():
                if (k.startswith("phone") or k.startswith("mobile")) and "__Comment" not in k and v:
                    tel = str(v)
                    break
        return Adresse(id=str(r.id), name=name.strip() or f"Adresse {r.id}", telefon=tel, roh=r.elements)

    def _adress_felder(self) -> list[str]:
        felder = list(self.cfg.get("adresse.name_felder", ["Vorname", "Name"]))
        felder += list(self.cfg.get("adresse.telefon_felder", ["defaultphone"]))
        for extra in (self.cfg.get("adresse.merkmal_feld"), self.cfg.get("adresse.letzter_kontakt_feld")):
            if extra:
                felder.append(extra)
        return list(dict.fromkeys(felder))

    def adressen(self, ids: Iterable[str]) -> dict[str, Adresse]:
        wanted = [i for i in dict.fromkeys(str(x) for x in ids) if i not in self._adress_cache]
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            recs = self.client.read("address", {"data": self._adress_felder(),
                                                "recordids": [int(x) for x in chunk],
                                                "listlimit": len(chunk)})
            for r in recs:
                a = self._to_adresse(r)
                self._adress_cache[a.id] = a
        return {i: self._adress_cache[str(i)] for i in ids if str(i) in self._adress_cache}

    def adressen_mit_merkmal(self, merkmal_key: str,
                             letzter_kontakt_vor: datetime | None = None) -> list[Adresse] | None:
        """None = Merkmal-Feld/-Wert nicht konfiguriert."""
        feld = self.cfg.get("adresse.merkmal_feld")
        wert = self.cfg.merkmal_wert(merkmal_key)
        if not feld or not wert:
            return None
        flt: dict[str, Any] = {feld: [{"op": "like", "val": f"%{wert}%"}]}
        lk = self.cfg.get("adresse.letzter_kontakt_feld")
        if letzter_kontakt_vor and lk:
            flt[lk] = [{"op": "<=", "val": fmt_api(letzter_kontakt_vor)}]
        recs = self.client.read_all("address", {"data": self._adress_felder(), "filter": flt})
        out = []
        for r in recs:
            a = self._to_adresse(r)
            self._adress_cache[a.id] = a
            out.append(a)
        return out

    # --- Objekte -------------------------------------------------------
    def _objekt_felder(self, extra: list[str] | None = None) -> list[str]:
        felder = [self.cfg.get("objekte.titel_feld", "objekttitel"),
                  self.cfg.get("objekte.nummer_feld", "objektnr_extern")]
        vb = self.cfg.get("objekte.vermarktungsbeginn_feld")
        if vb:
            felder.append(vb)
        felder += list(extra or [])
        return [f for f in dict.fromkeys(felder) if f]

    def _to_objekt(self, r: Record) -> Objekt:
        o = Objekt(id=str(r.id), titel=str(r.get(self.cfg.get("objekte.titel_feld", "objekttitel")) or ""),
                   nummer=str(r.get(self.cfg.get("objekte.nummer_feld", "objektnr_extern")) or ""),
                   roh=r.elements)
        self._objekt_cache[o.id] = o
        return o

    def objekte_gefiltert(self, filter_key: str, extra_felder: list[str] | None = None) -> list[Objekt]:
        flt = self.cfg.get(f"objekte.{filter_key}") or {}
        recs = self.client.read_all("estate", {"data": self._objekt_felder(extra_felder), "filter": flt})
        return [self._to_objekt(r) for r in recs]

    def objekte(self, ids: Iterable[str]) -> dict[str, Objekt]:
        wanted = [i for i in dict.fromkeys(str(x) for x in ids) if i and i not in self._objekt_cache]
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            recs = self.client.read("estate", {"data": self._objekt_felder(),
                                               "filter": {"Id": [{"op": "in", "val": [int(x) for x in chunk]}]},
                                               "listlimit": len(chunk)})
            for r in recs:
                self._to_objekt(r)
        return {str(i): self._objekt_cache[str(i)] for i in ids if str(i) in self._objekt_cache}

    # --- Termine (Get Appointments, resourcetype appointmentList) ------
    @staticmethod
    def _to_termin(r: Record) -> Termin:
        e = r.elements
        typ = e.get("type") or {}
        st = e.get("status") or {}
        dt = e.get("date") or {}
        est = e.get("estate") or {}
        return Termin(
            id=str(e.get("id") or r.id),
            betreff=str(e.get("subject") or ""),
            typ_value=str(typ.get("value") or "") if isinstance(typ, dict) else str(typ),
            typ_label=str(typ.get("label") or "") if isinstance(typ, dict) else str(typ),
            status=str(st.get("value") or "") if isinstance(st, dict) else str(st),
            start=parse_dt(dt.get("start")) if isinstance(dt, dict) else None,
            ende=parse_dt(dt.get("end")) if isinstance(dt, dict) else None,
            kontakt_ids=_ids(e.get("contacts")),
            objekt_id=(_ids(est) or [None])[0],
            ort=str(e.get("location") or "") if not isinstance(e.get("location"), dict) else "",
        )

    def termine(self, von: date, bis: date) -> list[Termin]:
        """Termine im Zeitraum (inkl.). Max 500 je Abfrage lt. Doku -> Zeitraum wird ggf. geteilt."""
        recs = self.client.get("appointmentList", {
            "data": TERMIN_FELDER,
            "filter": {"startDate": von.isoformat(), "endDate": bis.isoformat(), "isCancelled": False},
        })
        if len(recs) >= 500 and von < bis:
            mitte = von + (bis - von) // 2
            return self.termine(von, mitte) + self.termine(mitte + timedelta(days=1), bis)
        out = [self._to_termin(r) for r in recs]
        out = [t for t in out if t.status not in ("canceled", "cancelled")]
        out.sort(key=lambda t: (t.start is None, t.start))
        log.info("Termine %s..%s: %d", von, bis, len(out))
        return out

    # --- Aufgaben / Wiedervorlagen -------------------------------------
    def offene_aufgaben_je_adresse(self, adress_ids: list[str]) -> dict[str, list[Aufgabe]]:
        done_status = {str(s).lower() for s in (self.cfg.get("aufgaben.erledigt_status") or [])}
        out: dict[str, list[Aufgabe]] = {}
        ids = list(dict.fromkeys(adress_ids))
        for i in range(0, len(ids), MULTI_ACTION_CHUNK):
            chunk = ids[i:i + MULTI_ACTION_CHUNK]
            actions = [Action(ACTION_READ, "task", {"data": AUFGABE_FELDER, "relatedAddressId": int(a),
                                                    "listlimit": 100}, identifier=a) for a in chunk]
            for aid, res in zip(chunk, self.client.execute(actions)):
                tasks = []
                for r in self.client.records_of(res):
                    erledigt = str(r.get("erledigt") or "0").lower() in ("1", "true", "ja")
                    status = str(r.get("Status") or "")
                    if erledigt or status.lower() in done_status:
                        continue
                    tasks.append(Aufgabe(str(r.id), str(r.get("Betreff") or ""), parse_dt(r.get("Deadline")),
                                         status, erledigt))
                out[aid] = tasks
        return out

    # --- Konfiguration (für konfig-pruefen) -----------------------------
    def aktionsarten_im_system(self) -> dict[str, list[str]]:
        recs = self.client.get("actionkindtypes", {"lang": "DEU"})
        out: dict[str, list[str]] = {}
        for r in recs:
            key = str(r.get("key") or r.get("label") or "")
            types = r.get("types") or {}
            out[key] = list(types.keys()) if isinstance(types, dict) else list(types)
        return out

    def feldkonfiguration(self, module: list[str]) -> dict[str, dict[str, Any]]:
        recs = self.client.get("fields", {"labels": True, "language": "DEU", "modules": module})
        return {str(r.id): r.elements for r in recs}
