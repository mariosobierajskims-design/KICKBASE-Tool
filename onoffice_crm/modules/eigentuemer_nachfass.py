"""Phase 2 – Eigentümer-Nachfass (STUB).

Fällige MPE/Kaltakquise (core.regeln.faellige_nachfass) -> personalisierte Entwürfe aus Notizen
-> Freigabeliste an mich -> erst nach OK: sendmail + agentslog (über core.safety.VersandGuard).
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import RunContext
from .spaeter import stub

PHASE = 2


@dataclass
class NachfassEntwurf:
    adress_id: str
    betreff: str
    text: str
    grund: str              # z.B. "MPE Tag 56"
    freigegeben: bool = False


def entwuerfe_erstellen(ctx: RunContext) -> list[NachfassEntwurf]:  # pragma: no cover
    raise NotImplementedError("Phase 2")


def run(ctx: RunContext) -> int:
    return stub("eigentuemer_nachfass", PHASE, ctx)
