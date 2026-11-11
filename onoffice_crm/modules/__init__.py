"""Modul-Registry: CLI-Name -> Modulpfad. Neue Module hier eintragen."""
from __future__ import annotations

import importlib

MODULE = {
    # Phase 1
    "briefing": "modules.briefing",
    "wochenbericht": "modules.wochenbericht",
    "verbindungstest": "modules.verbindungstest",
    "konfig-pruefen": "modules.konfig_pruefen",
    # später (Stubs)
    "mpe_erfassung": "modules.mpe_erfassung",
    "eigentuemer_nachfass": "modules.eigentuemer_nachfass",
    "verkaeufer_update": "modules.verkaeufer_update",
    "auto_versand": "modules.auto_versand",
    "kleinanzeigen_assistent": "modules.kleinanzeigen_assistent",
}


def lade(name: str):
    return importlib.import_module(MODULE[name])
