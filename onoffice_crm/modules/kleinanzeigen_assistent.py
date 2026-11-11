"""Phase 4 – Kleinanzeigen-Assistent (STUB).

Liest NUR Suchauftrags-Benachrichtigungen aus einem eigenen Mailordner (IMAP), filtert
"keine Makler", erstellt Nachrichtenentwurf je Anzeige, legt Lead in onOffice an.
KEIN Scraping, keine Bots auf Portalen. Versand von Nachrichten ausschließlich manuell.
"""
from __future__ import annotations

from .base import RunContext
from .spaeter import stub

PHASE = 4


def run(ctx: RunContext) -> int:
    return stub("kleinanzeigen_assistent", PHASE, ctx)
