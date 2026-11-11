from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import AppConfig, Settings  # noqa: E402
from core.onoffice_client import OnOfficeClient  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.timeutil import TZ  # noqa: E402
from fake_api import SECRET, TOKEN, FakeSession  # noqa: E402
from modules.base import RunContext  # noqa: E402


@pytest.fixture
def cfg() -> AppConfig:
    c = AppConfig.load()
    c.data["adresse"]["merkmal_feld"] = "Merkmal_test"
    c.data["objekte"]["vermarktungsbeginn_feld"] = "vermarktungsstart"
    return c


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(session) -> OnOfficeClient:
    return OnOfficeClient(TOKEN, SECRET, "https://example.invalid/api.php", session=session,
                          min_interval=0, sleep=lambda s: None)


@pytest.fixture
def make_ctx(client, cfg, tmp_path):
    def _make(tag: str, **kw) -> RunContext:
        d = date.fromisoformat(tag)
        settings = Settings(onoffice_token=TOKEN, onoffice_secret=SECRET, mail_to="ich@example.org",
                            mail_from="ich@example.org", smtp_host="localhost")
        return RunContext(settings=settings, cfg=cfg, repo=Repository(client, cfg), heute=d,
                          jetzt=datetime(d.year, d.month, d.day, 9, 30, tzinfo=TZ), **kw)
    return _make
