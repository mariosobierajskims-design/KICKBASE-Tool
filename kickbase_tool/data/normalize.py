from typing import Optional

from kickbase_tool.data.models import Fixture, MatchdayEntry, Player, TableEntry
from kickbase_tool.util import as_list, pick


def normalize_player(raw: dict) -> Player:
    pid = pick(raw, "id", "i", "pid", "playerId")
    team_id = pick(raw, "teamId", "tid", "team_id")
    return Player(
        id=str(pid),
        first_name=str(pick(raw, "firstName", "fn", "first_name", default="")),
        last_name=str(pick(raw, "lastName", "ln", "n", "name", "last_name", default="")),
        team_id=str(team_id) if team_id is not None else None,
        position=pick(raw, "position", "pos"),
        status=pick(raw, "status", "st"),
        market_value=_to_float(pick(raw, "marketValue", "mv", "market_value")),
        season_average_points=_to_float(pick(raw, "averagePoints", "ap", "avgPoints", "average_points")),
    )


def normalize_performance_entry(raw: dict, fallback_team_id: Optional[str]) -> MatchdayEntry:
    matchday = pick(raw, "day", "matchday", "md", "dayNumber", "dn")
    points = _to_float(pick(raw, "points", "p", "pt"))
    minutes = pick(raw, "minutesPlayed", "minutes", "min", "mp")
    started = pick(raw, "startingEleven", "started", "isStarter", "so", "wasStarter")
    goals = pick(raw, "goals", "g", default=0) or 0
    assists = pick(raw, "assists", "a", default=0) or 0
    clean_sheet = bool(pick(raw, "cleanSheet", "cs", "keptCleanSheet", default=False))
    team_id = pick(raw, "teamId", "tid", default=fallback_team_id)
    opponent_team_id = pick(raw, "opponentTeamId", "otid", "opponentId", "oid")
    home = pick(raw, "home", "isHome", "h")

    # "played" has to be inferred: the API may omit entries for matchdays the
    # player did not feature in at all, or it may include a zero-point /
    # zero-minute placeholder entry for them. Either way, presence of a real
    # points value or recorded minutes/start counts as "played".
    played = points is not None or (isinstance(minutes, (int, float)) and minutes > 0) or bool(started)

    return MatchdayEntry(
        matchday=int(matchday) if matchday is not None else -1,
        played=bool(played),
        started=bool(started) if started is not None else False,
        points=points,
        minutes=int(minutes) if isinstance(minutes, (int, float)) else None,
        goals=int(goals),
        assists=int(assists),
        clean_sheet=clean_sheet,
        home=bool(home) if home is not None else None,
        team_id=str(team_id) if team_id is not None else None,
        opponent_team_id=str(opponent_team_id) if opponent_team_id is not None else None,
    )


def normalize_table_entry(raw: dict) -> TableEntry:
    team_id = pick(raw, "teamId", "tid", "id")
    return TableEntry(
        team_id=str(team_id),
        team_name=str(pick(raw, "teamName", "tn", "name", default=str(team_id))),
        position=int(pick(raw, "position", "pos", "rank", "place", default=0)),
    )


def normalize_fixture(raw: dict) -> Fixture:
    home_id = pick(raw, "homeTeamId", "t1", "homeId", "th")
    away_id = pick(raw, "awayTeamId", "t2", "awayId", "ta")
    finished = pick(raw, "finished", "isFinished", "status")
    if isinstance(finished, str):
        finished = finished.lower() in ("finished", "final", "done", "true")
    elif isinstance(finished, int):
        # some Kickbase endpoints use small status codes where a higher
        # number means "further along" / finished; 0/1 usually mean
        # scheduled/live. Treat anything >= 2 as finished, matching common
        # community usage, but this is unverified for v4.
        finished = finished >= 2
    return Fixture(
        matchday=int(pick(raw, "day", "matchday", "md", "dayNumber", default=0)),
        home_team_id=str(home_id),
        away_team_id=str(away_id),
        finished=bool(finished),
    )


def extract_player_list(raw: dict) -> list:
    return as_list(raw, "players", "it", "pl", "items")


def extract_performance_list(raw: dict) -> list:
    return as_list(raw, "it", "items", "performance", "matchdays")


def extract_table_list(raw: dict) -> list:
    return as_list(raw, "table", "it", "items", "teams")


def extract_fixture_list(raw: dict) -> list:
    return as_list(raw, "matchdays", "it", "items", "matches")


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
