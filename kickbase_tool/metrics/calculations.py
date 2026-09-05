from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from kickbase_tool.data.models import Fixture, Player, TableEntry
from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.fallback import RecentForm, compute_recent_form
from kickbase_tool.util import mean, rank_with_ties

RECENT_FORM_WINDOW = 5
TEAM_FORM_WINDOW = 5
UPCOMING_FIXTURES_WINDOW = 5


@dataclass
class PlayerMetrics:
    player: Player

    season_average: Optional[float]
    recent_form: RecentForm
    market_value: Optional[float]
    points_per_market_value: Optional[float]

    team_form: Optional[float]
    opponent_form: Optional[float]
    table_position_diff: Optional[float]

    own_venue_form: Optional[float]
    opponent_venue_form: Optional[float]
    venue_form_diff: Optional[float]

    goals: int
    assists: int
    clean_sheets: int

    next_opponent_team_id: Optional[str]
    next_opponent_name: Optional[str]
    next_match_is_home: Optional[bool]
    # Informational only (not a ranking category, see README) -- the next
    # UPCOMING_FIXTURES_WINDOW opponents with name/table position/venue, and
    # the average opponent table position across them.
    upcoming_opponents: List[dict]
    remaining_schedule_difficulty: Optional[float]

    # "Formsteigerung" (momentum): current rolling-5-game form rank (1=best
    # among all 18 teams) plus the change vs. the same rank two matchdays
    # ago -- low value = strong AND still improving, so a bad recent game
    # doesn't by itself flag a player at a genuinely in-form club. See
    # README "Formsteigerung" for the exact definition. None until enough
    # matchdays exist (needs >= 7: a 5-game window plus a 2-matchday-old
    # comparison point).
    team_momentum: Optional[float]
    opponent_momentum: Optional[float]


TeamPointsByMatchday = Dict[Tuple[str, int], float]
VenueMap = Dict[Tuple[str, int], bool]  # (team_id, matchday) -> is_home


def build_team_points_by_matchday(players: List[Player]) -> TeamPointsByMatchday:
    """Kickbase does not expose a direct 'team points per matchday' endpoint, so
    it is derived by summing the actual fantasy points of every player of a
    team who played on that matchday (per the confirmed approach for #8/#9)."""
    totals: TeamPointsByMatchday = {}
    for player in players:
        for entry in player.matchdays:
            if not entry.played or entry.points is None:
                continue
            team_id = entry.team_id or player.team_id
            if not team_id:
                continue
            key = (team_id, entry.matchday)
            totals[key] = totals.get(key, 0.0) + entry.points
    return totals


def build_venue_map(fixtures: List[Fixture]) -> VenueMap:
    venue: VenueMap = {}
    for fixture in fixtures:
        venue[(fixture.home_team_id, fixture.matchday)] = True
        venue[(fixture.away_team_id, fixture.matchday)] = False
    return venue


def _team_matchdays(team_points: TeamPointsByMatchday, team_id: str) -> List[int]:
    return sorted(md for (tid, md) in team_points if tid == team_id)


def team_form(team_points: TeamPointsByMatchday, team_id: str, window: int = TEAM_FORM_WINDOW) -> Optional[float]:
    matchdays = _team_matchdays(team_points, team_id)[-window:]
    if not matchdays:
        return None
    return mean(team_points[(team_id, md)] for md in matchdays)


def team_venue_form(
    team_points: TeamPointsByMatchday, venue: VenueMap, team_id: str, home: bool
) -> Optional[float]:
    matchdays = sorted(
        md for (tid, md) in team_points if tid == team_id and venue.get((tid, md)) == home
    )
    if not matchdays:
        return None
    return mean(team_points[(team_id, md)] for md in matchdays)


def build_team_rolling_form_ranks(
    team_points: TeamPointsByMatchday, all_team_ids: List[str], window: int = TEAM_FORM_WINDOW
) -> Dict[str, Dict[int, float]]:
    """For every matchday d where a full trailing `window`-matchday points sum
    can be formed, ranks all teams that have one (1 = highest sum = best
    form). Returns {team_id: {matchday: rank}}."""
    matchdays = sorted({md for (_tid, md) in team_points})
    ranks: Dict[str, Dict[int, float]] = {tid: {} for tid in all_team_ids}
    for d in matchdays:
        window_mds = range(d - window + 1, d + 1)
        sums = {}
        for tid in all_team_ids:
            if all((tid, m) in team_points for m in window_mds):
                sums[tid] = sum(team_points[(tid, m)] for m in window_mds)
        if not sums:
            continue
        for tid, rk in rank_with_ties(sums, higher_is_better=True).items():
            ranks[tid][d] = rk
    return ranks


def team_momentum(rolling_form_ranks: Dict[str, Dict[int, float]], team_id: str, trend_gap: int = 2) -> Optional[float]:
    """"Formsteigerung": aktueller Form-Rang + (aktueller Form-Rang - Form-Rang
    von vor `trend_gap` Spieltagen). Niedriger = besser UND im Aufwaertstrend."""
    ranks_for_team = rolling_form_ranks.get(team_id) or {}
    if not ranks_for_team:
        return None
    current_matchday = max(ranks_for_team)
    previous_matchday = current_matchday - trend_gap
    if previous_matchday not in ranks_for_team:
        return None
    current_rank = ranks_for_team[current_matchday]
    previous_rank = ranks_for_team[previous_matchday]
    return current_rank + (current_rank - previous_rank)


def next_fixture_for_team(fixtures: List[Fixture], team_id: str) -> Optional[Fixture]:
    upcoming = [
        f for f in fixtures if not f.finished and team_id in (f.home_team_id, f.away_team_id)
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda f: f.matchday)


def next_n_fixtures_for_team(fixtures: List[Fixture], team_id: str, n: int) -> List[Fixture]:
    upcoming = sorted(
        (f for f in fixtures if not f.finished and team_id in (f.home_team_id, f.away_team_id)),
        key=lambda f: f.matchday,
    )
    return upcoming[:n]


def opponent_in_fixture(fixture: Fixture, team_id: str) -> str:
    return fixture.away_team_id if fixture.home_team_id == team_id else fixture.home_team_id


def compute_all_metrics(dataset: Dataset) -> Dict[str, PlayerMetrics]:
    team_points = build_team_points_by_matchday(dataset.players)
    venue = build_venue_map(dataset.fixtures)
    table_by_team: Dict[str, TableEntry] = dataset.table_by_team
    rolling_form_ranks = build_team_rolling_form_ranks(team_points, list(table_by_team.keys()))

    results: Dict[str, PlayerMetrics] = {}
    for player in dataset.players:
        entries_desc = player.matchdays_desc()
        recent = compute_recent_form(entries_desc)

        season_points = [e.points for e in player.matchdays if e.played and e.points is not None]
        season_average = player.season_average_points if player.season_average_points is not None else mean(season_points)

        points_per_value = None
        if season_average is not None and player.market_value:
            points_per_value = season_average / player.market_value

        own_team_id = player.team_id
        own_form = team_form(team_points, own_team_id) if own_team_id else None

        next_fixture = next_fixture_for_team(dataset.fixtures, own_team_id) if own_team_id else None
        opponent_id = opponent_in_fixture(next_fixture, own_team_id) if next_fixture else None
        opponent_form = team_form(team_points, opponent_id) if opponent_id else None

        table_diff = None
        if own_team_id in table_by_team and opponent_id in table_by_team:
            table_diff = table_by_team[opponent_id].position - table_by_team[own_team_id].position

        is_home_next = None
        own_venue_form = opponent_venue_form = venue_form_diff = None
        if next_fixture is not None and own_team_id:
            is_home_next = next_fixture.home_team_id == own_team_id
            own_venue_form = team_venue_form(team_points, venue, own_team_id, is_home_next)
            if opponent_id:
                opponent_venue_form = team_venue_form(team_points, venue, opponent_id, not is_home_next)
            if own_venue_form is not None and opponent_venue_form is not None:
                venue_form_diff = own_venue_form - opponent_venue_form

        # Season totals, sourced directly from the player-detail endpoint --
        # confirmed live that per-matchday performance entries carry no
        # goal/assist/clean-sheet breakdown, only the running points total.
        goals = player.season_goals
        assists = player.season_assists
        clean_sheets = player.season_clean_sheets

        next_opponent_name = table_by_team[opponent_id].team_name if opponent_id in table_by_team else opponent_id

        upcoming_opponents = []
        if own_team_id:
            for f in next_n_fixtures_for_team(dataset.fixtures, own_team_id, UPCOMING_FIXTURES_WINDOW):
                opp_id = opponent_in_fixture(f, own_team_id)
                opp_entry = table_by_team.get(opp_id)
                upcoming_opponents.append({
                    "matchday": f.matchday,
                    "team_id": opp_id,
                    "team_name": opp_entry.team_name if opp_entry else opp_id,
                    "position": opp_entry.position if opp_entry else None,
                    "home": f.home_team_id == own_team_id,
                })
        remaining_difficulty = mean(
            o["position"] for o in upcoming_opponents if o["position"] is not None
        ) if upcoming_opponents else None

        own_momentum = team_momentum(rolling_form_ranks, own_team_id) if own_team_id else None
        opp_momentum = team_momentum(rolling_form_ranks, opponent_id) if opponent_id else None

        results[player.id] = PlayerMetrics(
            player=player,
            season_average=season_average,
            recent_form=recent,
            market_value=player.market_value,
            points_per_market_value=points_per_value,
            team_form=own_form,
            opponent_form=opponent_form,
            table_position_diff=table_diff,
            own_venue_form=own_venue_form,
            opponent_venue_form=opponent_venue_form,
            venue_form_diff=venue_form_diff,
            goals=goals,
            assists=assists,
            clean_sheets=clean_sheets,
            next_opponent_team_id=opponent_id,
            next_opponent_name=next_opponent_name,
            next_match_is_home=is_home_next,
            upcoming_opponents=upcoming_opponents,
            remaining_schedule_difficulty=remaining_difficulty,
            team_momentum=own_momentum,
            opponent_momentum=opp_momentum,
        )
    return results
