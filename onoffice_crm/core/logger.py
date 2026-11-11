"""Logging mit Datenschutz: Secrets, E-Mail-Adressen und Telefonnummern werden maskiert.

Grundsatz: In Logs nur IDs, Zähler, Laufzeiten -- keine Namen, keine Notiz-Volltexte.
Die Maskierung ist ein zusätzliches Sicherheitsnetz, kein Ersatz dafür.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d /()-]{6,}\d")


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 4]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        text = EMAIL_RE.sub("<email>", text)
        text = PHONE_RE.sub("<tel>", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        record.msg = self.redact(msg)
        record.args = ()
        return True


_configured = False
_redact = RedactingFilter()


def setup_logging(level: str = "INFO", log_dir: str | Path | None = "logs",
                  secrets: list[str] | None = None) -> logging.Logger:
    global _configured
    root = logging.getLogger("crm")
    root.setLevel(level)
    _redact.secrets = [s for s in (secrets or []) if s and len(s) >= 4]
    if _configured:
        return root
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redact = _redact
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redact)
    root.addHandler(console)
    if log_dir:
        path = Path(log_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        path.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(path / "crm.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(redact)
        root.addHandler(fh)
    root.propagate = False
    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"crm.{name}")
