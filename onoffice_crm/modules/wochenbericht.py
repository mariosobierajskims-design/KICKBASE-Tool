"""Phase 1 – Wochenbericht (Fr 15:00) an mich, als Entwurf für den Chef. NUR LESEN.

Zählt Maklerbuch-Aktivitäten Mo 00:00 – Fr 23:59 der laufenden Woche und vergleicht
mit derselben Spanne der Vorwoche. Zähler-Gruppen kommen aus config.yaml (wochenbericht.zaehler).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from core.regeln import zaehle
from core.timeutil import end_of_day, fmt_de, start_of_day, wochen_grenzen

from .base import Abschnitt, Eintrag, RunContext, ausgeben, render_html, render_text


@dataclass
class Zeile:
    name: str
    aktuell: int
    vorwoche: int

    @property
    def diff(self) -> int:
        return self.aktuell - self.vorwoche

    @property
    def diff_text(self) -> str:
        return f"{self.diff:+d}" if self.diff else "±0"


@dataclass
class Wochenzahlen:
    kw: int
    von: object
    bis: object
    zeilen: list[Zeile] = field(default_factory=list)
    fehlend: list[str] = field(default_factory=list)


def berechne(ctx: RunContext) -> Wochenzahlen:
    cfg, repo = ctx.cfg, ctx.repo
    mo, fr = wochen_grenzen(ctx.heute)
    gruppen_cfg: dict[str, list[str]] = cfg.get("wochenbericht.zaehler") or {}
    gruppen = {name: cfg.aktionsarten(list(keys)) for name, keys in gruppen_cfg.items()}
    fehlend = [n for n, specs in gruppen.items() if not specs]
    alle = [s for specs in gruppen.values() for s in specs]
    akts = repo.aktivitaeten(seit=start_of_day(mo - timedelta(days=7)), bis=end_of_day(fr), arten=alle) if alle else []
    grenze = start_of_day(mo)
    vorwoche_ende = end_of_day(fr - timedelta(days=7))
    akt = [a for a in akts if a.datum and a.datum >= grenze]
    vor = [a for a in akts if a.datum and a.datum < grenze and a.datum <= vorwoche_ende]
    z_akt, z_vor = zaehle(akt, gruppen), zaehle(vor, gruppen)
    zeilen = [Zeile(n, z_akt[n], z_vor[n]) for n in gruppen]
    return Wochenzahlen(ctx.heute.isocalendar()[1], mo, fr, zeilen, fehlend)


def entwurf_text(z: Wochenzahlen) -> str:
    """Kurzer Fließtext-Entwurf zum Weiterleiten an den Chef."""
    teile = [f"{zl.aktuell} {zl.name}" for zl in z.zeilen if zl.aktuell]
    staerker = [zl.name for zl in z.zeilen if zl.diff > 0]
    schwaecher = [zl.name for zl in z.zeilen if zl.diff < 0]
    s = f"Hallo, kurz die Zahlen der KW {z.kw} ({fmt_de(z.von)[:6]}–{fmt_de(z.bis)}): "
    s += (", ".join(teile) if teile else "keine erfassten Aktivitäten") + "."
    if staerker:
        s += f" Mehr als Vorwoche: {', '.join(staerker)}."
    if schwaecher:
        s += f" Weniger als Vorwoche: {', '.join(schwaecher)}."
    return s


def run(ctx: RunContext) -> int:
    z = berechne(ctx)
    titel = f"Wochenbericht KW {z.kw} (Entwurf)"
    abschnitt = Abschnitt("wochenzahlen", f"Aktivitäten {fmt_de(z.von)[:6]}–{fmt_de(z.bis)} vs. Vorwoche",
                          [Eintrag(f"{zl.name}: {zl.aktuell}", [f"Vorwoche {zl.vorwoche} ({zl.diff_text})"])
                           for zl in z.zeilen],
                          hinweis=f"Nicht konfiguriert: {', '.join(z.fehlend)}" if z.fehlend else None)
    entwurf = entwurf_text(z)
    html = render_html("wochenbericht.html", titel=titel, z=z, entwurf=entwurf, hinweis=abschnitt.hinweis,
                       fuss="Entwurf – vor dem Weiterleiten prüfen · nur lesend erstellt")
    text = render_text(titel, [abschnitt], f"Entwurf:\n{entwurf}")
    ausgeben(ctx, "wochenbericht", titel, html, text)
    return 0
