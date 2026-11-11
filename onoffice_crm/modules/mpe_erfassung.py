"""Phase 2 – MPE-Erfassung (STUB, nur Interface).

Input: Freitext / Sprachnotiz-Transkript -> strukturiertes Schema -> Adresse/Objekt/Aktivität
in onOffice (create/modify, über client.write => DRY_RUN + allow_write) + Danke-Mail-ENTWURF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import RunContext
from .spaeter import stub

PHASE = 2


@dataclass
class Objektdaten:
    objektart: str | None = None
    adresse: str | None = None
    wohnflaeche_m2: float | None = None
    grundstueck_m2: float | None = None
    zimmer: float | None = None
    baujahr: int | None = None


@dataclass
class MPEErfassung:
    objekt: Objektdaten = field(default_factory=Objektdaten)
    zustand: str | None = None
    motiv: str | None = None
    zeitrahmen: str | None = None
    preis_eigentuemer: float | None = None
    preis_einschaetzung: float | None = None
    einwaende: list[str] = field(default_factory=list)
    entscheider: list[str] = field(default_factory=list)
    persoenliche_details: list[str] = field(default_factory=list)
    naechster_schritt: str | None = None


def parse_freitext(text: str) -> MPEErfassung:  # pragma: no cover - Phase 2
    raise NotImplementedError("Phase 2")


def run(ctx: RunContext) -> int:
    return stub("mpe_erfassung", PHASE, ctx)
