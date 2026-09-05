from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from kickbase_tool.api import endpoints
from kickbase_tool.api.cache import JsonFileCache
from kickbase_tool.api.client import KickbaseAPIError, KickbaseClient
from kickbase_tool.config import Settings
from kickbase_tool.data.models import Fixture, Player, TableEntry
from kickbase_tool.data.normalize import (
    extract_fixture_list,
    extract_performance_list,
    extract_player_list,
    extract_table_list,
    normalize_fixture,
    normalize_performance_entry,
    normalize_player,
    normalize_table_entry,
)
from kickbase_tool.util import as_list, pick


class Dataset:
    def __init__(self, players: List[Player], table: List[TableEntry], fixtures: List[Fixture]):
        self.players = players
        self.table = table
        self.fixtures = fixtures
        self.table_by_team = {t.team_id: t for t in table}


def load_dataset(client: KickbaseClient, settings: Settings, force_refresh: bool = False) -> Dataset:
    cache = JsonFileCache(Path(settings.cache_dir))

    players_raw = cache.get_or_fetch(
        "competition_players",
        settings.cache_ttl_volatile_seconds,
        lambda: client.get(endpoints.COMPETITION_PLAYERS.format(competition_id=settings.competition_id)),
        force_refresh=force_refresh,
    )
    players = [normalize_player(p) for p in extract_player_list(players_raw)]

    table_raw = cache.get_or_fetch(
        "competition_table",
        settings.cache_ttl_volatile_seconds,
        lambda: client.get(endpoints.COMPETITION_TABLE.format(competition_id=settings.competition_id)),
        force_refresh=force_refresh,
    )
    table = [normalize_table_entry(t) for t in extract_table_list(table_raw)]

    matchdays_raw = cache.get_or_fetch(
        "competition_matchdays",
        settings.cache_ttl_volatile_seconds,
        lambda: client.get(endpoints.COMPETITION_MATCHDAYS.format(competition_id=settings.competition_id)),
        force_refresh=force_refresh,
    )
    fixtures = _normalize_fixtures(matchdays_raw)

    _attach_performance(client, settings, cache, players, force_refresh=force_refresh)

    return Dataset(players=players, table=table, fixtures=fixtures)


def _normalize_fixtures(matchdays_raw) -> List[Fixture]:
    """The /matchdays endpoint is expected to group matches per matchday
    (`{day, matches: [...]}`), but may also return a flat list of matches
    that already carry their own day number. Both shapes are handled.
    """
    top_level = extract_fixture_list(matchdays_raw)
    fixtures: List[Fixture] = []
    for entry in top_level:
        if not isinstance(entry, dict):
            continue
        nested_matches = as_list(entry, "matches", "it", "items")
        if nested_matches:
            day = pick(entry, "day", "matchday", "md", "dayNumber")
            for match in nested_matches:
                if day is not None and "day" not in match and "matchday" not in match:
                    match = {**match, "day": day}
                fixtures.append(normalize_fixture(match))
        else:
            fixtures.append(normalize_fixture(entry))
    return fixtures


def _attach_performance(
    client: KickbaseClient,
    settings: Settings,
    cache: JsonFileCache,
    players: List[Player],
    force_refresh: bool,
) -> None:
    def fetch_one(player: Player):
        def do_fetch():
            try:
                return client.get(
                    endpoints.COMPETITION_PLAYER_PERFORMANCE.format(
                        competition_id=settings.competition_id, player_id=player.id
                    )
                )
            except KickbaseAPIError:
                return {}

        raw = cache.get_or_fetch(
            f"performance_{player.id}",
            settings.cache_ttl_performance_seconds,
            do_fetch,
            force_refresh=force_refresh,
        )
        player.matchdays = [
            normalize_performance_entry(entry, fallback_team_id=player.team_id)
            for entry in extract_performance_list(raw)
        ]

    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = {pool.submit(fetch_one, p): p for p in players}
        for future in as_completed(futures):
            future.result()
