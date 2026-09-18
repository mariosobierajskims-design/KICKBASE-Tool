from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from kickbase_tool.data.models import Fixture, Player, TableEntry
from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.fallback import RecentForm, compute_recent_form
from kickbase_tool.util import mean, rank_with_ties

RECENT_FORM_WINDOW = 5
TEAM_FORM_WINDOW = 5
UPCOMING_FIXTURES_WINDOW = 5
# Wie viele rollierende TEAM_FORM_WINDOW-Formwerte in die geglaettete
# Mannschaftsform einfliessen (Nutzer-Korrektur: Team-Form ist kein reiner
# Letzte-5-Spiele-Schnitt mehr, sondern selbst schon ein "Zwischenwert" F_d,
# der ueber die letzten bis zu TEAM_FORM_SMOOTHING_WINDOW dieser Formwerte
# gemittelt wird -- siehe team_form()).
TEAM_FORM_SMOOTHING_WINDOW = 5
# Gestaffelte Gewichte fuers Restprogramm des EIGENEN Teams (Nutzer-Korrektur):
# der naechste Gegner zaehlt am staerksten, jeder weitere Gegner abgestuft
# weniger -- statt eines reinen (ungewichteten) Durchschnitts der naechsten
# UPCOMING_FIXTURES_WINDOW Gegner-Tabellenplaetze. Reihenfolge = Reihenfolge
# der Spieltage (naechster zuerst), Laenge folgt UPCOMING_FIXTURES_WINDOW.
UPCOMING_FIXTURES_WEIGHTS = [5, 4, 3, 2, 1]


@dataclass
class PlayerMetrics:
    player: Player

    season_average: Optional[float]
    recent_form: RecentForm
    market_value: Optional[float]
    points_per_market_value: Optional[float]

    team_form: Optional[float]
    opponent_form: Optional[float]
    # table_position_diff no longer uses the official Bundesliga table position
    # -- on explicit user request it's now based on a self-built "form table"
    # (all 18 teams ranked 1=best by their own rolling-5-game team_form value).
    # table_position_diff = form_rank(opponent) - form_rank(own team); positive
    # = own team in better form-table shape than the opponent (favourite role).
    table_position_diff: Optional[float]

    # Heim/Auswaerts (Kennzahl 11), restructured into 3 independently-weighted
    # columns on explicit user request: the own team's rank and the opponent's
    # rank in whichever venue table applies to each side of the next fixture
    # (home team judged by the home-table, away team by the away-table), plus
    # their difference. 1 = strongest team at that venue.
    #
    # Data source: real official Bundesliga home/away points-per-game via
    # OpenLigaDB (kickbase_tool/data/openligadb.py) -- confirmed live
    # 2026-09-09 to match this Kickbase competition's 18-team roster exactly
    # for season "2026" (2026/27). Falls back to a Kickbase-internal
    # fantasy-points estimate (build_team_venue_ranks' own computation, same
    # source the old venue_form_diff field used) if the OpenLigaDB fetch
    # fails or a team can't be matched -- see Dataset.home_venue_points.
    own_venue_rank: Optional[float]
    opponent_venue_rank: Optional[float]
    venue_rank_diff: Optional[float]

    goals: int
    assists: int
    clean_sheets: int

    next_opponent_team_id: Optional[str]
    next_opponent_name: Optional[str]
    next_match_is_home: Optional[bool]
    # Informational only (not a ranking category, see README) -- the next
    # UPCOMING_FIXTURES_WINDOW opponents with name/table position/venue, and
    # a GESTAFFELT gewichteter Durchschnitt der Gegner-Tabellenplaetze
    # (Nutzer-Korrektur: der naechste Gegner zaehlt am staerksten, siehe
    # UPCOMING_FIXTURES_WEIGHTS/_weighted_position_average) statt eines
    # reinen Durchschnitts.
    upcoming_opponents: List[dict]
    remaining_schedule_difficulty: Optional[float]
    # Same computation as remaining_schedule_difficulty, but UNGEWICHTET
    # (reiner Durchschnitt) und fuer die eigene Restlaufzeit des naechsten
    # OPPONENTEN statt des eigenen Teams -- bleibt bewusst ungewichtet, da
    # dieser Wert (anders als remaining_schedule_difficulty) direkt in
    # ranking/scoring.py als Ranking-Kategorie einfliesst und die Gewichtung
    # nur fuer die reine Info-Spalte des eigenen Teams angefragt wurde.
    opponent_remaining_schedule_difficulty: Optional[float]

    # "Formsteigerung" (Nutzer-Korrektur): Differenz zwischen dem aktuellsten
    # rollierenden 5-Spiele-Formwert (F_current, siehe team_form()) und dem
    # Formwert TREND_GAP Spieltage zuvor (F_current-2) -- rohe Punktedifferenz,
    # NICHT mehr rang-basiert. Positiv = Team gewinnt an Form, negativ = Team
    # verliert an Form. None, bis mindestens 3 vollstaendige rollierende
    # Formwerte existieren (siehe team_momentum()).
    team_momentum: Optional[float]
    opponent_momentum: Optional[float]

    # Startelf-Wahrscheinlichkeit + taegliche Marktwert-Aenderung, pass-through
    # von Player (siehe data/models.py) fuer das Gebotsmodell in
    # kickbase_tool/bidding/ -- bewusst kein eigenes Ranking-Kriterium (siehe
    # weights.yaml-Kommentar zu Kennzahl 13), nur Rohdaten-Durchreichung.
    # Defaults halten bestehende Konstruktor-Aufrufe (u.a. in tests/test_scoring.py)
    # funktionsfaehig, ohne dass diese Felder dort explizit gesetzt werden muessen.
    start_probability: Optional[int] = None
    market_value_change_day: Optional[float] = None


TeamPointsByMatchday = Dict[Tuple[str, int], float]
VenueMap = Dict[Tuple[str, int], bool]  # (team_id, matchday) -> is_home
VenueRanks = Dict[str, float]  # team_id -> rank (1 = strongest at that venue)


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


def _rolling_form_value(
    team_points: TeamPointsByMatchday, team_id: str, end_matchday: int, window: int = TEAM_FORM_WINDOW
) -> Optional[float]:
    """Schritt 1 (Nutzer-Korrektur): Durchschnitt der KICKBASE-Punkte des Teams
    aus genau den `window` Spieltagen, die auf `end_matchday` enden -- None,
    falls dieses Fenster noch nicht vollstaendig gespielt ist."""
    window_mds = range(end_matchday - window + 1, end_matchday + 1)
    if not all((team_id, m) in team_points for m in window_mds):
        return None
    return mean(team_points[(team_id, m)] for m in window_mds)


def team_form(
    team_points: TeamPointsByMatchday,
    team_id: str,
    window: int = TEAM_FORM_WINDOW,
    smoothing_window: int = TEAM_FORM_SMOOTHING_WINDOW,
) -> Optional[float]:
    """Geglaettete Mannschaftsform (Nutzer-Korrektur): NICHT mehr der einfache
    Durchschnitt der letzten `window` Spiele, sondern der Durchschnitt der
    letzten bis zu `smoothing_window` rollierenden `window`-Spiele-Formwerte
    (Schritt 1+2) -- z.B. bei Spieltag 12 mean(F8,F9,F10,F11,F12). Vor dem
    ersten vollstaendigen Fenster (weniger als `window` Saisonspiele absolviert)
    dient als Uebergangsloesung der einfache Durchschnitt aller bisher
    gespielten Saisonspiele."""
    matchdays = _team_matchdays(team_points, team_id)
    if not matchdays:
        return None
    latest_matchday = matchdays[-1]
    rolling_values: List[float] = []
    md = latest_matchday
    while len(rolling_values) < smoothing_window and md >= window:
        value = _rolling_form_value(team_points, team_id, md, window)
        if value is None:
            break
        rolling_values.append(value)
        md -= 1
    if not rolling_values:
        return mean(team_points[(team_id, m)] for m in matchdays)
    return mean(rolling_values)


def team_venue_form(
    team_points: TeamPointsByMatchday, venue: VenueMap, team_id: str, home: bool
) -> Optional[float]:
    matchdays = sorted(
        md for (tid, md) in team_points if tid == team_id and venue.get((tid, md)) == home
    )
    if not matchdays:
        return None
    return mean(team_points[(team_id, md)] for md in matchdays)


def build_team_venue_ranks(
    team_points: TeamPointsByMatchday,
    venue: VenueMap,
    all_team_ids: List[str],
    official_home_points: Optional[Dict[str, float]] = None,
    official_away_points: Optional[Dict[str, float]] = None,
) -> Tuple[VenueRanks, VenueRanks]:
    """Ranks all teams by their home-venue and away-venue strength separately
    (1 = strongest at that venue). Prefers the real official Bundesliga
    points-per-game passed in via official_home_points/official_away_points
    (see PlayerMetrics.own_venue_rank / kickbase_tool/data/openligadb.py);
    falls back to Kickbase's own per-matchday fantasy points split by venue
    when that's empty (network failure or no team match)."""
    if official_home_points and official_away_points:
        home_values = {tid: official_home_points.get(tid) for tid in all_team_ids}
        away_values = {tid: official_away_points.get(tid) for tid in all_team_ids}
    else:
        home_values = {tid: team_venue_form(team_points, venue, tid, home=True) for tid in all_team_ids}
        away_values = {tid: team_venue_form(team_points, venue, tid, home=False) for tid in all_team_ids}
    return (
        rank_with_ties(home_values, higher_is_better=True),
        rank_with_ties(away_values, higher_is_better=True),
    )


def build_form_table_ranks(team_points: TeamPointsByMatchday, all_team_ids: List[str]) -> Dict[str, float]:
    """Self-built 'form table': ranks all teams 1=best by their own rolling
    TEAM_FORM_WINDOW-game team_form value, instead of the official Bundesliga
    table position. Used for table_position_diff on explicit user request."""
    values = {tid: team_form(team_points, tid) for tid in all_team_ids}
    return rank_with_ties(values, higher_is_better=True)


def team_momentum(
    team_points: TeamPointsByMatchday,
    team_id: str,
    window: int = TEAM_FORM_WINDOW,
    trend_gap: int = 2,
) -> Optional[float]:
    """"Formsteigerung" (Nutzer-Korrektur, Schritt 4): rohe Punktedifferenz
    zwischen dem aktuellsten rollierenden `window`-Spiele-Formwert (F_current)
    und dem Formwert `trend_gap` Spieltage zuvor (F_current-2) -- NICHT mehr
    rang-basiert. Positiv = Team gewinnt an Form, negativ = verliert an Form.
    Erst definiert, sobald mindestens 3 vollstaendige rollierende Formwerte
    existieren (bei window=5/trend_gap=2 also ab Spieltag 7: F5,F6,F7)."""
    matchdays = _team_matchdays(team_points, team_id)
    if not matchdays:
        return None
    latest_matchday = matchdays[-1]
    if latest_matchday < window + trend_gap:
        return None
    current_value = _rolling_form_value(team_points, team_id, latest_matchday, window)
    previous_value = _rolling_form_value(team_points, team_id, latest_matchday - trend_gap, window)
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


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


def _weighted_position_average(opponents: List[dict], weights: List[float] = UPCOMING_FIXTURES_WEIGHTS) -> Optional[float]:
    """Gestaffelt gewichteter Durchschnitt der Gegner-Tabellenplaetze (Nutzer-
    Korrektur): `opponents` ist bereits nach Spieltag sortiert (naechster
    zuerst), `weights` ordnet dem naechsten Gegner das groesste Gewicht zu und
    faellt danach ab. Fehlt fuer weniger Gegner ein Teil der Liste (z.B.
    Saisonende), werden einfach die vorderen (groessten) Gewichte der
    verbleibenden Anzahl verwendet -- die Normierung ueber die Summe der
    tatsaechlich genutzten Gewichte haelt die Reihenfolge (naechster zaehlt am
    meisten) in jedem Fall korrekt."""
    pairs = [(o["position"], w) for o, w in zip(opponents, weights) if o["position"] is not None]
    if not pairs:
        return None
    total_weight = sum(w for _, w in pairs)
    return sum(pos * w for pos, w in pairs) / total_weight


def _remaining_schedule_difficulty(
    fixtures: List[Fixture],
    table_by_team: Dict[str, TableEntry],
    team_id: Optional[str],
    weighted: bool = False,
) -> Tuple[List[dict], Optional[float]]:
    """Returns the next UPCOMING_FIXTURES_WINDOW opponents (with name/table
    position/venue) for `team_id`, plus a difficulty score across them (None
    if there is no team_id or no upcoming fixtures). `weighted=True` (Nutzer-
    Korrektur, fuer die eigene Restprogramm-Info-Spalte) uses the staggered
    _weighted_position_average instead of the plain mean -- the ranking
    category opponent_remaining_schedule_difficulty stays on the plain mean
    (weighted=False, its established behaviour)."""
    if not team_id:
        return [], None
    opponents = []
    for f in next_n_fixtures_for_team(fixtures, team_id, UPCOMING_FIXTURES_WINDOW):
        opp_id = opponent_in_fixture(f, team_id)
        opp_entry = table_by_team.get(opp_id)
        opponents.append({
            "matchday": f.matchday,
            "team_id": opp_id,
            "team_name": opp_entry.team_name if opp_entry else opp_id,
            "position": opp_entry.position if opp_entry else None,
            "home": f.home_team_id == team_id,
        })
    if not opponents:
        return opponents, None
    if weighted:
        difficulty = _weighted_position_average(opponents)
    else:
        difficulty = mean(o["position"] for o in opponents if o["position"] is not None)
    return opponents, difficulty


def compute_all_metrics(dataset: Dataset) -> Dict[str, PlayerMetrics]:
    team_points = build_team_points_by_matchday(dataset.players)
    venue = build_venue_map(dataset.fixtures)
    table_by_team: Dict[str, TableEntry] = dataset.table_by_team
    all_team_ids = list(table_by_team.keys())
    form_table_ranks = build_form_table_ranks(team_points, all_team_ids)
    home_venue_ranks, away_venue_ranks = build_team_venue_ranks(
        team_points, venue, all_team_ids,
        official_home_points=dataset.home_venue_points, official_away_points=dataset.away_venue_points,
    )

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
        if own_team_id in form_table_ranks and opponent_id in form_table_ranks:
            table_diff = form_table_ranks[opponent_id] - form_table_ranks[own_team_id]

        is_home_next = None
        own_venue_rank = opponent_venue_rank = venue_rank_diff = None
        if next_fixture is not None and own_team_id:
            is_home_next = next_fixture.home_team_id == own_team_id
            own_table, opp_table = (home_venue_ranks, away_venue_ranks) if is_home_next else (away_venue_ranks, home_venue_ranks)
            own_venue_rank = own_table.get(own_team_id)
            if opponent_id:
                opponent_venue_rank = opp_table.get(opponent_id)
            if own_venue_rank is not None and opponent_venue_rank is not None:
                venue_rank_diff = opponent_venue_rank - own_venue_rank

        # Season totals, sourced directly from the player-detail endpoint --
        # confirmed live that per-matchday performance entries carry no
        # goal/assist/clean-sheet breakdown, only the running points total.
        goals = player.season_goals
        assists = player.season_assists
        clean_sheets = player.season_clean_sheets

        next_opponent_name = table_by_team[opponent_id].team_name if opponent_id in table_by_team else opponent_id

        upcoming_opponents, remaining_difficulty = _remaining_schedule_difficulty(
            dataset.fixtures, table_by_team, own_team_id, weighted=True
        )
        _, opponent_remaining_difficulty = _remaining_schedule_difficulty(
            dataset.fixtures, table_by_team, opponent_id, weighted=False
        )

        own_momentum = team_momentum(team_points, own_team_id) if own_team_id else None
        opp_momentum = team_momentum(team_points, opponent_id) if opponent_id else None

        results[player.id] = PlayerMetrics(
            player=player,
            season_average=season_average,
            recent_form=recent,
            market_value=player.market_value,
            points_per_market_value=points_per_value,
            team_form=own_form,
            opponent_form=opponent_form,
            table_position_diff=table_diff,
            own_venue_rank=own_venue_rank,
            opponent_venue_rank=opponent_venue_rank,
            venue_rank_diff=venue_rank_diff,
            goals=goals,
            assists=assists,
            clean_sheets=clean_sheets,
            next_opponent_team_id=opponent_id,
            next_opponent_name=next_opponent_name,
            next_match_is_home=is_home_next,
            upcoming_opponents=upcoming_opponents,
            remaining_schedule_difficulty=remaining_difficulty,
            opponent_remaining_schedule_difficulty=opponent_remaining_difficulty,
            team_momentum=own_momentum,
            opponent_momentum=opp_momentum,
            start_probability=player.start_probability,
            market_value_change_day=player.market_value_change_day,
        )
    return results
