"""Prüft config.yaml gegen das Live-System (nur lesen) und hilft beim Ausfüllen.

- Aktionsarten/-typen: Abgleich mit 'Get kind/type' (resourcetype actionkindtypes)
- Merkmal-Feld: listet Multiselect-Felder des Adressmoduls mit erlaubten Werten (Get Field Configuration)
- Objekt-Felder: zeigt Datumsfelder des Objektmoduls (für vermarktungsbeginn_feld)
"""
from __future__ import annotations

from .base import RunContext


def run(ctx: RunContext) -> int:
    repo, cfg = ctx.repo, ctx.cfg
    probleme = 0

    print("== Aktionsarten (config.yaml -> onOffice) ==")
    system = repo.aktionsarten_im_system()
    system_lc = {k.lower(): (k, [t.lower() for t in v]) for k, v in system.items()}
    for key in (cfg.data.get("aktionsarten") or {}):
        specs = cfg.aktionsart(key)
        if not specs:
            print(f"  -  {key}: nicht gesetzt")
            continue
        for s in specs:
            treffer = system_lc.get(s.aktionsart.lower())
            if not treffer:
                print(f"  ✗  {key}: Aktionsart '{s.aktionsart}' existiert nicht")
                probleme += 1
            elif s.aktionstyp and s.aktionstyp.lower() not in treffer[1]:
                print(f"  ✗  {key}: Aktionstyp '{s.aktionstyp}' fehlt bei '{treffer[0]}'")
                probleme += 1
            else:
                print(f"  ✓  {key}: {s.aktionsart}{' / ' + s.aktionstyp if s.aktionstyp else ''}")
    print("\n  Im System vorhanden:")
    for k, typen in sorted(system.items()):
        print(f"    {k}: {', '.join(typen) if typen else '(keine Typen)'}")

    print("\n== Adressfelder (Multiselect/Singleselect) – Kandidaten für adresse.merkmal_feld ==")
    felder = repo.feldkonfiguration(["address", "estate"])
    adr = felder.get("address", {})
    for name, info in sorted(adr.items()):
        if isinstance(info, dict) and info.get("type") in ("multiselect", "singleselect"):
            werte = info.get("permittedvalues") or {}
            vorschau = ", ".join(f"{k}={v}" for k, v in list(werte.items())[:12]) if isinstance(werte, dict) else ""
            print(f"  {name} ({info.get('label', '')}, {info.get('type')}): {vorschau}")
    feld = cfg.get("adresse.merkmal_feld")
    if feld:
        info = adr.get(feld)
        if not info:
            print(f"  ✗  adresse.merkmal_feld '{feld}' existiert nicht")
            probleme += 1
        else:
            erlaubt = set((info.get("permittedvalues") or {}).keys())
            for key, wert in (cfg.data.get("merkmale") or {}).items():
                ok = str(wert) in erlaubt
                probleme += 0 if ok else 1
                print(f"  {'✓' if ok else '✗'}  merkmale.{key} = {wert}")

    print("\n== Objekt-Datumsfelder – Kandidaten für objekte.vermarktungsbeginn_feld ==")
    for name, info in sorted(felder.get("estate", {}).items()):
        if isinstance(info, dict) and info.get("type") in ("date", "datetime"):
            print(f"  {name} ({info.get('label', '')})")

    print(f"\n{probleme} Problem(e) gefunden." if probleme else "\nKonfiguration passt.")
    return 1 if probleme else 0
