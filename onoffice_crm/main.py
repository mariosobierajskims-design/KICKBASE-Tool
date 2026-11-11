"""CLI: python main.py <modul> [--dry-run] [--console] [--datum YYYY-MM-DD]

Beispiele:
  python main.py verbindungstest
  python main.py konfig-pruefen
  python main.py briefing --console            # Text in Konsole, keine Mail
  python main.py briefing --dry-run            # HTML nach out/, keine Mail
  python main.py briefing                      # Mail an MAIL_TO
  python main.py briefing --console --datum 2026-11-10   # Wochentag simulieren
  python main.py wochenbericht
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import AppConfig, ConfigError, Settings  # noqa: E402
from core.logger import get_logger, setup_logging  # noqa: E402
from core.mailer import MailError  # noqa: E402
from core.onoffice_client import OnOfficeAuthError, OnOfficeClient, OnOfficeError  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.timeutil import TZ  # noqa: E402
from modules import MODULE, lade  # noqa: E402
from modules.base import RunContext  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CRM-Automatisierung onOffice (Phase 1: nur lesen)")
    p.add_argument("modul", choices=sorted(MODULE))
    p.add_argument("--dry-run", action="store_true", help="keine Mail senden, HTML nach out/ schreiben")
    p.add_argument("--console", action="store_true", help="Ausgabe als Text in die Konsole (keine Mail)")
    p.add_argument("--datum", help="Stichtag simulieren (YYYY-MM-DD), z.B. um einen Wochentag zu testen")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.log_dir, settings.secrets())
    log = get_logger("main")
    try:
        cfg = AppConfig.load()
        jetzt = datetime.now(TZ)
        heute = date.fromisoformat(args.datum) if args.datum else jetzt.date()
        settings.require_api()
        api = cfg.get("api") or {}
        client = OnOfficeClient(
            settings.onoffice_token, settings.onoffice_secret, settings.onoffice_api_url,
            timeout=api.get("timeout_s", 30), max_retries=api.get("max_retries", 3),
            min_interval=api.get("min_abstand_s", 0.4), page_size=api.get("seitengroesse", 500),
            max_records=api.get("max_datensaetze", 5000),
            allow_write=False,          # Phase 1: Schreiben hart gesperrt
            dry_run=True,
        )
        ctx = RunContext(settings=settings, cfg=cfg, repo=Repository(client, cfg), heute=heute, jetzt=jetzt,
                         dry_run=args.dry_run, console=args.console, args=args)
        log.info("Start %s (Stichtag %s, dry_run=%s, console=%s)", args.modul, heute, args.dry_run, args.console)
        return lade(args.modul).run(ctx)
    except ConfigError as exc:
        log.error("Konfiguration: %s", exc)
        return 3
    except OnOfficeAuthError as exc:
        log.error("onOffice-Authentifizierung: %s", exc)
        return 4
    except OnOfficeError as exc:
        log.error("onOffice-API: %s", exc)
        return 5
    except MailError as exc:
        log.error("Mail: %s", exc)
        return 6


if __name__ == "__main__":
    sys.exit(main())
