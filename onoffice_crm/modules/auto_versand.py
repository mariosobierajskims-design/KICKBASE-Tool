"""Phase 3 – Auto-Versand (STUB).

Geplant: Stufe-1-Erinnerung (_agreementLink), Besichtigungsbestätigung Vortag,
Besichtigungs-Nachfass Mo/Do, 3D-Link Stufe 2/3, Unterlagen bei Aktivität unterlagen_angefragt,
Eigentümer-Opt-in -> MPE-Angebot.

Pflicht für jeden Versand: core.safety.VersandGuard.pruefe() (Kill-Switch, keine_automatik,
Agreement-Pflicht, max 1 Auto-Mail/3 Tage, Testmodus-Whitelist), danach agentslog-Eintrag
und Eintrag ins tägliche Versandprotokoll an mich. Versand über onOffice sendmail
(resourcetype "sendmail", action do) -> client.write() => DRY_RUN greift.
"""
from __future__ import annotations

from .base import RunContext
from .spaeter import stub

PHASE = 3


def run(ctx: RunContext) -> int:
    return stub("auto_versand", PHASE, ctx)
