"""Laden von .env (Secrets) und config.yaml (fachliche Konfiguration)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_API_URL = "https://api.onoffice.de/api/stable/api.php"


class ConfigError(Exception):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass(frozen=True)
class Settings:
    """Werte aus .env. Secrets werden in repr() nie ausgegeben."""

    onoffice_token: str = field(default="", repr=False)
    onoffice_secret: str = field(default="", repr=False)
    onoffice_api_url: str = DEFAULT_API_URL
    dry_run: bool = True
    automation_enabled: bool = False
    testmode: bool = True
    test_whitelist: tuple[str, ...] = ()
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)
    mail_from: str = field(default="", repr=False)
    mail_to: str = field(default="", repr=False)
    log_level: str = "INFO"
    log_dir: str = "logs"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or PROJECT_DIR / ".env", override=False)
        g = os.environ.get
        return cls(
            onoffice_token=g("ONOFFICE_TOKEN", "").strip(),
            onoffice_secret=g("ONOFFICE_SECRET", "").strip(),
            onoffice_api_url=(g("ONOFFICE_API_URL") or DEFAULT_API_URL).strip(),
            dry_run=_bool(g("DRY_RUN"), True),
            automation_enabled=_bool(g("AUTOMATION_ENABLED"), False),
            testmode=_bool(g("TESTMODE"), True),
            test_whitelist=tuple(
                a.strip().lower() for a in (g("TEST_WHITELIST") or "").split(",") if a.strip()
            ),
            smtp_host=g("SMTP_HOST", "").strip(),
            smtp_port=int(g("SMTP_PORT") or 587),
            smtp_security=(g("SMTP_SECURITY") or "starttls").strip().lower(),
            smtp_user=g("SMTP_USER", "").strip(),
            smtp_password=g("SMTP_PASSWORD", ""),
            mail_from=g("MAIL_FROM", "").strip(),
            mail_to=g("MAIL_TO", "").strip(),
            log_level=(g("LOG_LEVEL") or "INFO").upper(),
            log_dir=g("LOG_DIR") or "logs",
        )

    def require_api(self) -> None:
        if not self.onoffice_token or not self.onoffice_secret:
            raise ConfigError("ONOFFICE_TOKEN / ONOFFICE_SECRET fehlen in .env")

    def require_mail(self) -> None:
        missing = [n for n, v in (("SMTP_HOST", self.smtp_host), ("MAIL_FROM", self.mail_from),
                                  ("MAIL_TO", self.mail_to)) if not v]
        if missing:
            raise ConfigError(f"Fehlende Mail-Einstellungen in .env: {', '.join(missing)}")

    def secrets(self) -> list[str]:
        """Werte, die in Logs maskiert werden."""
        return [s for s in (self.onoffice_token, self.onoffice_secret, self.smtp_password) if s]


@dataclass(frozen=True)
class AktionsartSpec:
    """Eine Aktionsart (+ optional Aktionstyp) wie in onOffice gepflegt."""

    aktionsart: str
    aktionstyp: str | None = None

    def matches(self, aktionsart: str | None, aktionstyp: str | None) -> bool:
        if (aktionsart or "").strip().lower() != self.aktionsart.strip().lower():
            return False
        if self.aktionstyp is None:
            return True
        return (aktionstyp or "").strip().lower() == self.aktionstyp.strip().lower()


class AppConfig:
    """Zugriff auf config.yaml mit Hilfsfunktionen."""

    def __init__(self, data: dict[str, Any]):
        self.data = data or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or PROJECT_DIR / "config.yaml"
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh) or {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # --- Aktionsarten -------------------------------------------------
    def aktionsart(self, key: str) -> list[AktionsartSpec]:
        """Liefert die Specs für einen Schlüssel; leere Liste = nicht konfiguriert."""
        raw = (self.data.get("aktionsarten") or {}).get(key)
        return _parse_specs(raw)

    def aktionsarten(self, keys: list[str]) -> list[AktionsartSpec]:
        out: list[AktionsartSpec] = []
        for k in keys:
            out.extend(self.aktionsart(k))
        return out

    def merkmal_wert(self, key: str) -> str | None:
        val = (self.data.get("merkmale") or {}).get(key)
        return str(val) if val not in (None, "") else None

    def intervall(self, key: str, default: Any = None) -> Any:
        return (self.data.get("intervalle") or {}).get(key, default)


def _parse_specs(raw: Any) -> list[AktionsartSpec]:
    if raw in (None, "", []):
        return []
    if isinstance(raw, list):
        out: list[AktionsartSpec] = []
        for item in raw:
            out.extend(_parse_specs(item))
        return out
    if isinstance(raw, str):
        return [AktionsartSpec(raw)]
    if isinstance(raw, dict) and raw.get("aktionsart"):
        typ = raw.get("aktionstyp")
        return [AktionsartSpec(str(raw["aktionsart"]), str(typ) if typ else None)]
    raise ConfigError(f"Ungültiger Aktionsart-Eintrag in config.yaml: {raw!r}")
