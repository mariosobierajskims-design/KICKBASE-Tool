"""Gemeinsame Bausteine für Module: Laufkontext, Abschnitte, Rendering, Ausgabe."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.config import PROJECT_DIR, AppConfig, Settings
from core.logger import get_logger
from core.mailer import send_to_self
from core.repository import Repository

log = get_logger("modules")

_env = Environment(loader=FileSystemLoader(PROJECT_DIR / "templates"),
                   autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


@dataclass
class RunContext:
    settings: Settings
    cfg: AppConfig
    repo: Repository | None
    heute: date
    jetzt: datetime
    dry_run: bool = True
    console: bool = False
    args: Any = None


@dataclass
class Eintrag:
    titel: str
    zeilen: list[str] = field(default_factory=list)
    tag: str = ""
    wichtig: bool = False


@dataclass
class Abschnitt:
    key: str
    titel: str
    eintraege: list[Eintrag] = field(default_factory=list)
    hinweis: str | None = None
    leer_text: str = "Nichts offen."
    max_eintraege: int | None = None

    @property
    def anzahl(self) -> int:
        return len(self.eintraege)

    @property
    def sichtbar(self) -> list[Eintrag]:
        return self.eintraege[: self.max_eintraege] if self.max_eintraege else self.eintraege

    @property
    def weitere(self) -> int:
        return max(self.anzahl - len(self.sichtbar), 0)


def render_html(template: str, **kw: Any) -> str:
    return _env.get_template(template).render(**kw)


def render_text(titel: str, abschnitte: list[Abschnitt], fuss: str = "") -> str:
    lines = [titel, "=" * len(titel), ""]
    for a in abschnitte:
        lines.append(f"## {a.titel} ({a.anzahl})")
        if a.hinweis:
            lines.append(f"   ! {a.hinweis}")
        if not a.eintraege and not a.hinweis:
            lines.append(f"   {a.leer_text}")
        for e in a.sichtbar:
            tag = f" [{e.tag}]" if e.tag else ""
            lines.append(f" - {e.titel}{tag}")
            for z in e.zeilen:
                lines.append(f"     {z}")
        if a.weitere:
            lines.append(f"   + {a.weitere} weitere")
        lines.append("")
    if fuss:
        lines.append(fuss)
    return "\n".join(lines)


def ausgeben(ctx: RunContext, name: str, betreff: str, html: str, text: str) -> None:
    """--console: Text auf stdout. --dry-run: HTML nach out/. Sonst: Mail an mich."""
    if ctx.console:
        print(text)
    if ctx.dry_run or ctx.console:
        out = PROJECT_DIR / "out"
        out.mkdir(exist_ok=True)
        path = out / f"{name}_{ctx.heute.isoformat()}.html"
        path.write_text(html, encoding="utf-8")
        log.info("Keine Mail (dry-run/console). HTML gespeichert: %s", path.relative_to(PROJECT_DIR))
        return
    send_to_self(ctx.settings, betreff, html, text)

