import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _default_bundesliga_season() -> str:
    """OpenLigaDB seasons are named by the year they START (e.g. "2026" =
    2026/27) -- Bundesliga seasons start in ~August, so before July the
    previous year's season is still the current one."""
    now = datetime.now(timezone.utc)
    return str(now.year if now.month >= 7 else now.year - 1)


@dataclass(frozen=True)
class Settings:
    email: Optional[str]
    password: Optional[str]
    auth_token: Optional[str]
    league_id: Optional[str]
    competition_id: str
    cache_dir: Path
    request_delay_seconds: float
    max_workers: int
    cache_ttl_volatile_seconds: float
    cache_ttl_performance_seconds: float
    # Kennzahl 11 (Heim/Auswaerts): real official Bundesliga home/away tables
    # come from the free OpenLigaDB API (kickbase_tool/data/openligadb.py),
    # not from Kickbase itself. See that module's docstring for why the
    # season parameter matters (must match Kickbase's currently tracked
    # real-world season) and how to override it if it ever drifts.
    openligadb_league_shortcut: str
    openligadb_season: str


def load_settings() -> Settings:
    email = os.environ.get("KICKBASE_EMAIL")
    password = os.environ.get("KICKBASE_PASSWORD")
    auth_token = os.environ.get("KICKBASE_AUTH_TOKEN")

    # Auth can happen either via email+password (the documented login endpoint)
    # or via a token captured manually from a logged-in browser session -- the
    # latter is required for accounts that only have "Sign in with Apple/Google"
    # linked, since Kickbase's login endpoint only accepts email+password and
    # there's no public API for exchanging a social login for a session token.
    has_credentials = bool(email and password)
    has_token = bool(auth_token)
    if not has_credentials and not has_token:
        raise RuntimeError(
            "Fehlende Angaben in der .env-Datei: entweder KICKBASE_EMAIL + "
            "KICKBASE_PASSWORD, oder KICKBASE_AUTH_TOKEN. Siehe .env.example."
        )

    # The core player database (Bundesliga-Spielerpool, Performance, Marktwerte,
    # Tabelle, Spielplan) is league-independent (/v4/competitions/... endpoints),
    # so KICKBASE_LEAGUE_ID is only needed for optional per-league extras
    # (eigener Kader/Markt) and is therefore not required here.
    league_id = os.environ.get("KICKBASE_LEAGUE_ID")

    return Settings(
        email=email,
        password=password,
        auth_token=auth_token,
        league_id=league_id,
        competition_id=os.environ.get("KICKBASE_COMPETITION_ID", "1"),
        cache_dir=Path(os.environ.get("KICKBASE_CACHE_DIR", ".cache")),
        request_delay_seconds=float(os.environ.get("KICKBASE_REQUEST_DELAY_SECONDS", "0.15")),
        max_workers=int(os.environ.get("KICKBASE_MAX_WORKERS", "6")),
        cache_ttl_volatile_seconds=float(os.environ.get("KICKBASE_CACHE_TTL_VOLATILE", "3600")),
        cache_ttl_performance_seconds=float(os.environ.get("KICKBASE_CACHE_TTL_PERFORMANCE", "3600")),
        openligadb_league_shortcut=os.environ.get("KICKBASE_OPENLIGADB_LEAGUE", "bl1"),
        openligadb_season=os.environ.get("KICKBASE_BL_SEASON", _default_bundesliga_season()),
    )


def authenticate(client, settings: Settings) -> None:
    if settings.auth_token:
        client.use_token(settings.auth_token)
    else:
        client.login(settings.email, settings.password)
