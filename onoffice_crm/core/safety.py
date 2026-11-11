"""Sicherungen für späteren Kundenversand (Phase 2/3). In Phase 1 nicht verdrahtet.

Jeder spätere Versand MUSS über VersandGuard.pruefe() laufen und danach
VersandProtokoll.eintragen() aufrufen (-> agentslog-Eintrag + Tagesprotokoll an mich).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import AppConfig, Settings


@dataclass
class KontaktStatus:
    """Vom Aufrufer aus onOffice ermittelt (Merkmale, Agreement, letzte Auto-Mail)."""

    adress_id: str
    email: str
    merkmale: set[str] = field(default_factory=set)     # config-Schlüssel, z.B. {"keine_automatik"}
    hat_agreement: bool = False
    letzte_automail: datetime | None = None


@dataclass
class Entscheidung:
    erlaubt: bool
    gruende: list[str]
    nur_simulation: bool = False


class VersandGuard:
    def __init__(self, settings: Settings, cfg: AppConfig):
        self.settings = settings
        self.cfg = cfg

    def pruefe(self, kontakt: KontaktStatus, inhalt_typ: str, jetzt: datetime) -> Entscheidung:
        gruende: list[str] = []
        if not self.settings.automation_enabled:
            gruende.append("Kill-Switch: AUTOMATION_ENABLED=false")
        if "keine_automatik" in kontakt.merkmale:
            gruende.append("Merkmal keine_automatik")
        pflicht = set(self.cfg.get("sicherungen.agreement_pflicht_fuer") or [])
        if inhalt_typ in pflicht and not kontakt.hat_agreement:
            gruende.append(f"Kein Agreement – {inhalt_typ} blockiert")
        min_tage = int(self.cfg.get("sicherungen.min_tage_zwischen_automails", 3))
        if kontakt.letzte_automail and jetzt - kontakt.letzte_automail < timedelta(days=min_tage):
            gruende.append(f"Letzte Auto-Mail < {min_tage} Tage")
        if self.settings.testmode and kontakt.email.strip().lower() not in self.settings.test_whitelist:
            gruende.append("Testmodus: Empfänger nicht auf Whitelist")
        if not kontakt.email:
            gruende.append("Keine E-Mail-Adresse")
        return Entscheidung(erlaubt=not gruende, gruende=gruende, nur_simulation=self.settings.dry_run)


@dataclass
class ProtokollEintrag:
    zeit: datetime
    adress_id: str
    inhalt_typ: str
    ergebnis: str           # gesendet | simuliert | blockiert
    gruende: list[str]


class VersandProtokoll:
    """Sammelt Versand-Entscheidungen für das tägliche Protokoll an mich.
    Persistenz/agentslog-Eintrag wird in Phase 3 ergänzt (create agentslog lt. Doku)."""

    def __init__(self) -> None:
        self.eintraege: list[ProtokollEintrag] = []

    def eintragen(self, e: ProtokollEintrag) -> None:
        self.eintraege.append(e)
