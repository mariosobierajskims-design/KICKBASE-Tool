import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    email: str
    password: str
    league_id: str
    competition_id: str
    cache_dir: Path
    request_delay_seconds: float
    max_workers: int
    cache_ttl_volatile_seconds: float
    cache_ttl_performance_seconds: float


def load_settings() -> Settings:
    email = os.environ.get("KICKBASE_EMAIL")
    password = os.environ.get("KICKBASE_PASSWORD")
    league_id = os.environ.get("KICKBASE_LEAGUE_ID")

    missing = [
        name
        for name, value in (
            ("KICKBASE_EMAIL", email),
            ("KICKBASE_PASSWORD", password),
            ("KICKBASE_LEAGUE_ID", league_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Fehlende Angaben in der .env-Datei: "
            + ", ".join(missing)
            + ". Siehe .env.example."
        )

    return Settings(
        email=email,
        password=password,
        league_id=league_id,
        competition_id=os.environ.get("KICKBASE_COMPETITION_ID", "1"),
        cache_dir=Path(os.environ.get("KICKBASE_CACHE_DIR", ".cache")),
        request_delay_seconds=float(os.environ.get("KICKBASE_REQUEST_DELAY_SECONDS", "0.15")),
        max_workers=int(os.environ.get("KICKBASE_MAX_WORKERS", "6")),
        cache_ttl_volatile_seconds=float(os.environ.get("KICKBASE_CACHE_TTL_VOLATILE", "3600")),
        cache_ttl_performance_seconds=float(os.environ.get("KICKBASE_CACHE_TTL_PERFORMANCE", "86400")),
    )
