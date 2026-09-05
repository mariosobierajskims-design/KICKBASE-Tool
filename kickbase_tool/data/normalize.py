from typing import Optional

from kickbase_tool.data.models import Fixture, MatchdayEntry, Player, TableEntry
from kickbase_tool.util import as_list, pick

# Field names below are confirmed against live /v4 responses captured via
# kickbase_tool/dump_raw.py (see raw_samples/) on 2026-09-05, not just
# guessed from public docs. Older guessed aliases are kept as fallbacks in
# case the shape differs for other endpoints/contexts.


def normalize_player_detail(raw: dict) -> Player:
    """Normalizes /v4/competitions/{competitionId}/players/{playerId} --
    confirmed fields: i, fn, ln, tid, pos, st, mv, ap, g, a, cs."""
    pid = pick(raw, "i", "id", "pi", "playerId")
    team_id = pick(raw, "tid", "teamId", "team_id")
    return Player(
        id=str(pid),
        first_name=str(pick(raw, "fn", "firstName", "first_name", default="")),
        last_name=str(pick(raw, "ln", "lastName", "n", "name", "last_name", default="")),
        team_id=str(team_id) if team_id is not None else None,
        position=pick(raw, "pos", "position"),
        status=pick(raw, "st", "status"),
        market_value=_to_float(pick(raw, "mv", "marketValue", "market_value")),
        season_average_points=_to_float(pick(raw, "ap", "averagePoints", "avgPoints", "average_points")),
        season_goals=int(pick(raw, "g", "goals", default=0) or 0),
        season_assists=int(pick(raw, "a", "assists", default=0) or 0),
        season_clean_sheets=int(pick(raw, "cs", "cleanSheets", default=0) or 0),
    )


def normalize_team_roster_entry(raw: dict) -> Player:
    """Normalizes one entry of /v4/competitions/{competitionId}/teams/{teamId}/teamprofile
    ("it" list). Used only to discover player ids per team cheaply; the
    authoritative per-player record (incl. g/a/cs) comes from
    normalize_player_detail() via a follow-up call."""
    return normalize_player_detail(raw)


def _current_season_block(performance_raw: dict) -> dict:
    """/players/{id}/performance groups per-matchday entries by season under
    "it" (one block per season the player has data for, each with an "sid").
    The current season isn't flagged explicitly, so the block with the
    highest sid (Kickbase's internal season id, confirmed monotonically
    increasing across the 2015/16..2026/27 seasons in a live sample) is used.
    """
    blocks = as_list(performance_raw, "it", "items")
    if not blocks:
        return {}
    return max(blocks, key=lambda b: int(pick(b, "sid", default=0) or 0))


def extract_current_season_performance(performance_raw: dict) -> list:
    """Returns only the FINISHED matchdays of the current season (mdst == 2)
    -- the API pre-populates the full season's future fixtures too (mdst == 0,
    no "p"/"mp" keys), which must not count as part of the "last N games"
    window used by the recent-form fallback logic."""
    block = _current_season_block(performance_raw)
    entries = as_list(block, "ph", "it", "items")
    return [e for e in entries if pick(e, "mdst", "mdstatus") == 2]


def normalize_performance_entry(raw: dict, fallback_team_id: Optional[str]) -> MatchdayEntry:
    matchday = pick(raw, "day", "matchday", "md", "dayNumber", "dn")
    points = _to_float(pick(raw, "p", "points", "pt"))
    minutes = _parse_minutes(pick(raw, "mp", "minutesPlayed", "minutes", "min"))
    # st==5 was confirmed live as "started"; other per-match codes (e.g. 3 for
    # a substitute appearance) are carried over from an older sample and
    # unverified for the current season's schema.
    match_status = pick(raw, "st")
    started = match_status == 5

    team1 = pick(raw, "t1", "homeTeamId", "th")
    team2 = pick(raw, "t2", "awayTeamId", "ta")
    team_id = fallback_team_id
    home = None
    opponent_team_id = None
    if team1 is not None and team2 is not None and fallback_team_id is not None:
        if str(team1) == str(fallback_team_id):
            home, opponent_team_id = True, team2
        elif str(team2) == str(fallback_team_id):
            home, opponent_team_id = False, team1

    played = points is not None

    return MatchdayEntry(
        matchday=int(matchday) if matchday is not None else -1,
        played=played,
        started=bool(started),
        points=points,
        minutes=minutes,
        home=home,
        team_id=str(team_id) if team_id is not None else None,
        opponent_team_id=str(opponent_team_id) if opponent_team_id is not None else None,
    )


def normalize_table_entry(raw: dict) -> TableEntry:
    team_id = pick(raw, "tid", "teamId", "id")
    return TableEntry(
        team_id=str(team_id),
        team_name=str(pick(raw, "tn", "teamName", "name", default=str(team_id))),
        position=int(pick(raw, "cpl", "position", "pos", "rank", "place", default=0)),
    )


def normalize_fixture(raw: dict) -> Fixture:
    home_id = pick(raw, "t1", "homeTeamId", "homeId", "th")
    away_id = pick(raw, "t2", "awayTeamId", "awayId", "ta")
    finished = pick(raw, "st", "finished", "isFinished", "status")
    if isinstance(finished, str):
        finished = finished.lower() in ("finished", "final", "done", "true")
    elif isinstance(finished, int):
        # Confirmed live: st == 2 means the match has finished; 0 means
        # scheduled/not yet played. Treating >= 2 as finished matches both.
        finished = finished >= 2
    return Fixture(
        matchday=int(pick(raw, "day", "matchday", "md", "dayNumber", default=0)),
        home_team_id=str(home_id),
        away_team_id=str(away_id),
        finished=bool(finished),
    )


def extract_player_list(raw: dict) -> list:
    return as_list(raw, "players", "it", "pl", "items")


def extract_table_list(raw: dict) -> list:
    return as_list(raw, "table", "it", "items", "teams")


def extract_fixture_list(raw: dict) -> list:
    return as_list(raw, "matchdays", "it", "items", "matches")


def _parse_minutes(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None
    return None


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
