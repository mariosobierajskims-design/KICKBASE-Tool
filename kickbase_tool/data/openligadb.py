"""Real official Bundesliga home/away tables, sourced from the free OpenLigaDB
API (https://www.openligadb.de/, no auth required) -- used for Kennzahl 11
(Heim/Auswaerts) on explicit user request, after two other sources turned out
unusable: kicker.de is blocked by this environment's egress proxy, and
transfermarkt.de is reachable but the OpenLigaDB JSON API avoids HTML scraping.

IMPORTANT (season alignment, confirmed live 2026-09-09): OpenLigaDB's season
parameter is the year the season STARTS, e.g. season "2026" is the 2026/27
season. Season "2025" (2025/26, already finished) has a materially different
18-team roster than this Kickbase competition (Heidenheim/St. Pauli/Wolfsburg
instead of Elversberg/Paderborn/Schalke) -- season "2026" was confirmed to
match Kickbase's 18 teams exactly (by team short-name, via
TEAM_NAME_ALIASES for the 3 that differ in spelling: Schalke/S04,
Hamburg/HSV, M'gladbach/Gladbach). If Kickbase's competition ever tracks a
different real-world season, KICKBASE_BL_SEASON in .env may need updating.
"""
from typing import Dict, List, Optional, Tuple

import requests

BASE_URL = "https://api.openligadb.de"
REQUEST_TIMEOUT_SECONDS = 15.0

# OpenLigaDB shortName -> Kickbase team_name, for the 3 clubs where they
# differ (see module docstring). All other clubs match by exact shortName ==
# Kickbase team_name (both confirmed live for the 2026/27 season).
TEAM_NAME_ALIASES = {
    "S04": "Schalke",
    "HSV": "Hamburg",
    "Gladbach": "M'gladbach",
}


def fetch_matches(league_shortcut: str, season: str) -> list:
    """Raises requests.RequestException on network/HTTP failure -- callers
    should catch broadly and degrade gracefully (see repository.load_dataset)
    since this is a supplementary data source, not the core Kickbase pipeline."""
    url = f"{BASE_URL}/getmatchdata/{league_shortcut}/{season}"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _final_score(match: dict) -> Optional[Tuple[int, int]]:
    if not match.get("matchIsFinished"):
        return None
    results = match.get("matchResults") or []
    final = next((r for r in results if r.get("resultTypeKind") == "After90Minutes"), None)
    if final is None and results:
        final = max(results, key=lambda r: r.get("resultOrderID", 0))
    if final is None or final.get("pointsTeam1") is None or final.get("pointsTeam2") is None:
        return None
    return final["pointsTeam1"], final["pointsTeam2"]


def compute_venue_points(matches: list) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """Returns (home_stats, away_stats): OpenLigaDB shortName -> {"points":
    total real football league points (3/1/0), "matches": count}, counting
    each team only for the matches it played at that venue."""
    home: Dict[str, dict] = {}
    away: Dict[str, dict] = {}
    for m in matches:
        score = _final_score(m)
        if score is None:
            continue
        goals1, goals2 = score
        team1 = (m.get("team1") or {}).get("shortName")
        team2 = (m.get("team2") or {}).get("shortName")
        if not team1 or not team2:
            continue
        if goals1 > goals2:
            points1, points2 = 3, 0
        elif goals1 < goals2:
            points1, points2 = 0, 3
        else:
            points1, points2 = 1, 1
        h = home.setdefault(team1, {"points": 0, "matches": 0})
        h["points"] += points1
        h["matches"] += 1
        a = away.setdefault(team2, {"points": 0, "matches": 0})
        a["points"] += points2
        a["matches"] += 1
    return home, away


def points_per_game(stats: Dict[str, dict]) -> Dict[str, float]:
    return {name: s["points"] / s["matches"] for name, s in stats.items() if s["matches"] > 0}


def map_shortnames_to_kickbase_ids(ppg_by_shortname: Dict[str, float], team_name_by_id: Dict[str, str]) -> Dict[str, float]:
    """team_name_by_id: Kickbase team_id -> team_name (e.g. from
    dataset.table_by_team). Unmatched OpenLigaDB teams are silently dropped
    (missing venue data for a team degrades gracefully -- see
    PlayerMetrics.own_venue_rank)."""
    name_to_id = {name: tid for tid, name in team_name_by_id.items()}
    result: Dict[str, float] = {}
    for shortname, value in ppg_by_shortname.items():
        kickbase_name = TEAM_NAME_ALIASES.get(shortname, shortname)
        team_id = name_to_id.get(kickbase_name)
        if team_id is not None:
            result[team_id] = value
    return result


def _match_matchday(match: dict) -> Optional[int]:
    """OpenLigaDB's matchday number for a match (e.g. "1. Spieltag" -> 1),
    used by metrics/matchup.py to restrict historical data to "everything
    before matchday N" for the walk-forward backtest (Nutzer-Vorgabe:
    "ohne Daten zukuenftiger Spieltage") -- None if the API response is
    missing the group info (degrades gracefully, see callers)."""
    group = match.get("group") or {}
    return group.get("groupOrderID")


def extract_finished_results(matches: list, team_name_by_id: Dict[str, str]) -> List[dict]:
    """Returns one dict per finished match with real outcome ("home"/"draw"/
    "away"), mapped to Kickbase team_ids -- used by metrics/matchup.py to
    CALIBRATE the Spielergebnis-Prognose thresholds against actual results
    this season, instead of inventing cutoff numbers. Matches that can't be
    mapped to a Kickbase team_id (unmatched shortName, see TEAM_NAME_ALIASES)
    are silently dropped, same degrade-gracefully approach as
    map_shortnames_to_kickbase_ids above.

    Also carries "matchday" (OpenLigaDB groupOrderID, may be None for an
    unexpected API shape) and the real "home_goals"/"away_goals" -- added for
    the Nutzer-Korrektur "erzielte und kassierte Tore ... in die Prognose
    einfliessen lassen" (metrics/matchup.py derives a goal-difference-per-
    venue factor from these) and for the walk-forward backtest (which needs
    to know EACH result's matchday to exclude anything from/after the
    matchday being predicted). Purely additive vs. the previous shape
    (home_team_id/away_team_id/outcome unchanged), so existing callers that
    only read those three keys are unaffected."""
    name_to_id = {name: tid for tid, name in team_name_by_id.items()}
    results: List[dict] = []
    for m in matches:
        score = _final_score(m)
        if score is None:
            continue
        goals1, goals2 = score
        team1 = (m.get("team1") or {}).get("shortName")
        team2 = (m.get("team2") or {}).get("shortName")
        if not team1 or not team2:
            continue
        home_id = name_to_id.get(TEAM_NAME_ALIASES.get(team1, team1))
        away_id = name_to_id.get(TEAM_NAME_ALIASES.get(team2, team2))
        if not home_id or not away_id:
            continue
        if goals1 > goals2:
            outcome = "home"
        elif goals1 < goals2:
            outcome = "away"
        else:
            outcome = "draw"
        results.append({
            "home_team_id": home_id, "away_team_id": away_id, "outcome": outcome,
            "matchday": _match_matchday(m), "home_goals": goals1, "away_goals": goals2,
        })
    return results


def fetch_venue_points_by_kickbase_id(
    league_shortcut: str, season: str, team_name_by_id: Dict[str, str]
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Fetches this season's finished matches and returns (home_ppg,
    away_ppg) keyed by Kickbase team_id. Lets requests.RequestException
    propagate -- callers decide how to degrade (see repository.load_dataset)."""
    matches = fetch_matches(league_shortcut, season)
    home_stats, away_stats = compute_venue_points(matches)
    home_ppg = points_per_game(home_stats)
    away_ppg = points_per_game(away_stats)
    return (
        map_shortnames_to_kickbase_ids(home_ppg, team_name_by_id),
        map_shortnames_to_kickbase_ids(away_ppg, team_name_by_id),
    )
