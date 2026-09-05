from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from kickbase_tool.api import endpoints
from kickbase_tool.api.cache import JsonFileCache
from kickbase_tool.api.client import KickbaseAPIError, KickbaseClient
from kickbase_tool.config import Settings
from kickbase_tool.data.models import Fixture, Player, TableEntry
from kickbase_tool.data.normalize import (
    extract_current_season_performance,
    extract_fixture_list,
    extract_player_list,
    extract_table_list,
    normalize_fixture,
    normalize_performance_entry,
    normalize_player_detail,
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

    player_ids_by_team = _fetch_team_rosters(client, settings, cache, table, force_refresh=force_refresh)
    players = _fetch_player_details_and_performance(client, settings, cache, player_ids_by_team, force_refresh=force_refresh)

    return Dataset(players=players, table=table, fixtures=fixtures)


def _normalize_fixtures(matchdays_raw) -> List[Fixture]:
    """The /matchdays endpoint groups matches per matchday
    (`{day, it: [...matches]}`), confirmed live; a flat list of matches that
    already carry their own day number is also handled defensively."""
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


def _fetch_team_rosters(
    client: KickbaseClient,
    settings: Settings,
    cache: JsonFileCache,
    table: List[TableEntry],
    force_refresh: bool,
) -> List[tuple]:
    """Returns a flat list of (player_id, team_id) by calling teamprofile once
    per team -- this is the only way to discover the full player pool, since
    COMPETITION_PLAYERS is scoped to the current matchday's two teams only."""

    def fetch_one(team: TableEntry):
        raw = cache.get_or_fetch(
            f"team_roster_{team.team_id}",
            settings.cache_ttl_volatile_seconds,
            lambda: client.get(
                endpoints.COMPETITION_TEAM_PROFILE.format(
                    competition_id=settings.competition_id, team_id=team.team_id
                )
            ),
            force_refresh=force_refresh,
        )
        return [
            (str(pick(p, "i", "id", "pi")), team.team_id)
            for p in extract_player_list(raw)
            if pick(p, "i", "id", "pi") is not None
        ]

    results: List[tuple] = []
    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = {pool.submit(fetch_one, team): team for team in table}
        for future in as_completed(futures):
            results.extend(future.result())
    return results


def _fetch_player_details_and_performance(
    client: KickbaseClient,
    settings: Settings,
    cache: JsonFileCache,
    player_ids_by_team: List[tuple],
    force_refresh: bool,
) -> List[Player]:
    def fetch_one(player_id: str, roster_team_id: str) -> Player:
        def fetch_detail():
            try:
                return client.get(
                    endpoints.COMPETITION_PLAYER_DETAIL.format(
                        competition_id=settings.competition_id, player_id=player_id
                    )
                )
            except KickbaseAPIError:
                return {}

        def fetch_performance():
            try:
                return client.get(
                    endpoints.COMPETITION_PLAYER_PERFORMANCE.format(
                        competition_id=settings.competition_id, player_id=player_id
                    )
                )
            except KickbaseAPIError:
                return {}

        detail_raw = cache.get_or_fetch(
            f"player_detail_{player_id}", settings.cache_ttl_volatile_seconds, fetch_detail, force_refresh=force_refresh
        )
        performance_raw = cache.get_or_fetch(
            f"performance_{player_id}",
            settings.cache_ttl_performance_seconds,
            fetch_performance,
            force_refresh=force_refresh,
        )

        player = normalize_player_detail(detail_raw) if detail_raw else Player(
            id=player_id, first_name="", last_name="", team_id=roster_team_id, position=None,
            status=None, market_value=None, season_average_points=None,
        )
        if not player.team_id:
            player.team_id = roster_team_id

        player.matchdays = [
            normalize_performance_entry(entry, fallback_team_id=player.team_id)
            for entry in extract_current_season_performance(performance_raw)
        ]
        return player

    players: List[Player] = []
    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = {pool.submit(fetch_one, pid, tid): pid for pid, tid in player_ids_by_team}
        for future in as_completed(futures):
            players.append(future.result())
    return players
