"""Schritt 3: API-Verbindungstest – liest genau 1 Adresse und 1 Objekt (nur IDs werden ausgegeben)."""
from __future__ import annotations

from core.logger import get_logger

from .base import RunContext

log = get_logger("verbindungstest")


def run(ctx: RunContext) -> int:
    client = ctx.repo.client
    adr = client.read("address", {"data": ["Name"], "listlimit": 1})
    print(f"✓ Adressen lesbar: {len(adr)} Datensatz gelesen (ID {adr[0].id if adr else '–'})")
    obj = client.read("estate", {"data": ["objekttitel"], "listlimit": 1})
    print(f"✓ Objekte lesbar: {len(obj)} Datensatz gelesen (ID {obj[0].id if obj else '–'})")
    akt = client.read("agentslog", {"data": ["Datum", "Aktionsart"], "listlimit": 1})
    print(f"✓ Maklerbuch lesbar: {len(akt)} Eintrag (Aktionsart vorhanden: {bool(akt and akt[0].get('Aktionsart'))})")
    if not adr and not obj:
        print("! Keine Datensätze: lt. Doku meist fehlende Leserechte des API-Benutzers ('nur eigene' reicht nicht).")
    log.info("Verbindungstest ok (%d Requests)", client.request_count)
    return 0
