from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from kickbase_tool.metrics.calculations import PlayerMetrics
from kickbase_tool.util import rank_with_ties

DEFAULT_WEIGHTS_PATH = Path(__file__).with_name("weights.yaml")

# category_key -> (extractor, higher_is_better)
# higher_is_better always describes what is good for OWNING/BUYING a player
# ("Aufstellung"/"Kauf" direction); "Verkauf" reuses the same categories and
# simply reverses every rank (see compute_ranking(reverse=True)).
CATEGORY_DEFINITIONS = {
    "season_avg": (lambda pm: pm.season_average, True),
    "recent_avg": (lambda pm: pm.recent_form.average, True),
    "recent_min": (lambda pm: pm.recent_form.minimum, True),
    "recent_max": (lambda pm: pm.recent_form.maximum, True),
    "recent_min_max_avg": (lambda pm: pm.recent_form.min_max_average, True),
    # Direction flipped on explicit user request: a higher market value is now
    # treated as a quality signal (proven/expensive player), not a cost to
    # minimize. Only used for Aufstellung -- Kauf/Verkauf use points_per_value
    # instead (see AUFSTELLUNG/KAUF_CATEGORIES below).
    "market_value": (lambda pm: pm.market_value, True),
    "points_per_value": (lambda pm: pm.points_per_market_value, True),
    "team_form": (lambda pm: pm.team_form, True),
    "opponent_form": (lambda pm: pm.opponent_form, False),  # weaker opponent = better for the player
    "table_position_diff": (lambda pm: pm.table_position_diff, True),
    # Heim/Auswaerts (Kennzahl 11), split into 3 independent categories on
    # explicit user request -- see PlayerMetrics.own_venue_rank for the
    # data-source caveat (Kickbase-internal fantasy points, not an official
    # real-world home/away table).
    "own_venue_rank": (lambda pm: pm.own_venue_rank, False),  # own team's rank at that venue: 1 = best
    "opponent_venue_rank": (lambda pm: pm.opponent_venue_rank, True),  # opponent's rank: weak (high number) = better for us
    "venue_rank_diff": (lambda pm: pm.venue_rank_diff, True),
    # Next-opponent categories beyond opponent_form, added on explicit user
    # request: a tougher remaining schedule for the opponent (numerically
    # LOW avg upcoming-opponent table position = strong future opponents for
    # them) is assumed good for our player, mirroring opponent_form's "weaker
    # opponent = better" convention.
    "opponent_remaining_schedule_difficulty": (lambda pm: pm.opponent_remaining_schedule_difficulty, False),
    # A weak/declining opponent (high raw momentum value) is good for us --
    # inverse of team_momentum's own "lower = stronger and rising" meaning.
    "opponent_momentum": (lambda pm: pm.opponent_momentum, True),
}

# Shared by all three rankings; Aufstellung adds market_value (see below),
# Kauf/Verkauf add points_per_value instead (on explicit user request: for
# Kauf/Verkauf the "value" signal is points-per-money, not raw market value).
BASE_CATEGORIES = [
    "season_avg", "recent_avg", "recent_min", "recent_max", "recent_min_max_avg",
    "team_form", "opponent_form", "table_position_diff",
    "own_venue_rank", "opponent_venue_rank", "venue_rank_diff",
    "goals_assists_cleansheets",
    "opponent_remaining_schedule_difficulty", "opponent_momentum",
]
AUFSTELLUNG_CATEGORIES = BASE_CATEGORIES + ["market_value"]
KAUF_CATEGORIES = BASE_CATEGORIES + ["points_per_value"]
VERKAUF_CATEGORIES = KAUF_CATEGORIES


@dataclass
class RankingResult:
    scores: Dict[str, float]  # player_id -> final average rank (lower = better)
    category_ranks: Dict[str, Dict[str, float]]  # category -> player_id -> rank
    order: List[str]  # player ids sorted best-first


def load_weights(path: Path = DEFAULT_WEIGHTS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Goals:assists:clean-sheets sub-weights within Kennzahl 12, taken from the
# user's own Google Sheet formula (=SUM(W*90+Y*35+AA*20)/145, where W/Y/AA are
# the rank-of-goals/assists/clean-sheets columns) -- goals count roughly 4.5x
# more than clean sheets, assists about 1.75x more.
GOALS_ASSISTS_CLEANSHEETS_WEIGHTS = {"goals": 90, "assists": 35, "clean_sheets": 20}


def _combined_goals_assists_cleansheets_rank(metrics_by_id: Dict[str, PlayerMetrics]) -> Dict[str, float]:
    """Kennzahl 12 bundles three raw stats (Tore, Vorlagen, zu-Null) into a single
    rank category, as required ("15 Kennzahlen" total). Each raw stat is ranked
    across the player pool on its own (higher = better), then the three ranks
    are combined with GOALS_ASSISTS_CLEANSHEETS_WEIGHTS into one composite value
    per player. That composite is itself already rank-like (lower = better), so
    it is exposed as a "lower is better" category to the generic ranking pipeline.
    """
    goals = {pid: pm.goals for pid, pm in metrics_by_id.items()}
    assists = {pid: pm.assists for pid, pm in metrics_by_id.items()}
    clean_sheets = {pid: pm.clean_sheets for pid, pm in metrics_by_id.items()}

    goal_ranks = rank_with_ties(goals, higher_is_better=True)
    assist_ranks = rank_with_ties(assists, higher_is_better=True)
    clean_sheet_ranks = rank_with_ties(clean_sheets, higher_is_better=True)

    w = GOALS_ASSISTS_CLEANSHEETS_WEIGHTS
    total_w = w["goals"] + w["assists"] + w["clean_sheets"]
    return {
        pid: (goal_ranks[pid] * w["goals"] + assist_ranks[pid] * w["assists"] + clean_sheet_ranks[pid] * w["clean_sheets"]) / total_w
        for pid in metrics_by_id
    }


def compute_ranking(
    metrics_by_id: Dict[str, PlayerMetrics],
    categories: List[str],
    weights: Dict[str, float],
    reverse: bool = False,
) -> RankingResult:
    n = len(metrics_by_id)
    combined_gac = _combined_goals_assists_cleansheets_rank(metrics_by_id)

    category_ranks: Dict[str, Dict[str, float]] = {}
    for category in categories:
        if category == "goals_assists_cleansheets":
            values = combined_gac
            higher_is_better = False  # already a rank (lower = better)
        else:
            extractor, higher_is_better = CATEGORY_DEFINITIONS[category]
            values = {pid: extractor(pm) for pid, pm in metrics_by_id.items()}

        ranks = rank_with_ties(values, higher_is_better=higher_is_better)
        if reverse:
            ranks = {pid: (n + 1 - r) for pid, r in ranks.items()}
        category_ranks[category] = ranks

    total_weight = sum(weights.get(c, 1.0) for c in categories) or 1.0
    scores: Dict[str, float] = {}
    for pid in metrics_by_id:
        scores[pid] = sum(weights.get(c, 1.0) * category_ranks[c][pid] for c in categories) / total_weight

    order = sorted(scores, key=lambda pid: scores[pid])
    return RankingResult(scores=scores, category_ranks=category_ranks, order=order)


def compute_all_rankings(
    metrics_by_id: Dict[str, PlayerMetrics], weights_path: Path = DEFAULT_WEIGHTS_PATH
) -> Dict[str, RankingResult]:
    """Verletzte/gesperrte/angeschlagene Spieler werden NICHT mehr aus den
    Rankings ausgeschlossen (frueher ein harter Filter) -- auf Nutzerwunsch
    fliessen sie ganz normal mit ihren echten Werten ein, damit sie nicht aus
    Versehen uebersehen werden, falls sie am naechsten Spieltag doch spielen.
    Der Status bleibt nur eine Anzeige-Spalte; die Entscheidung, ob so ein
    Spieler trotzdem beruecksichtigt wird, trifft der Nutzer manuell."""
    weights = load_weights(weights_path)
    return {
        "aufstellung": compute_ranking(metrics_by_id, AUFSTELLUNG_CATEGORIES, weights.get("aufstellung", {})),
        "kauf": compute_ranking(metrics_by_id, KAUF_CATEGORIES, weights.get("kauf", {})),
        "verkauf": compute_ranking(metrics_by_id, VERKAUF_CATEGORIES, weights.get("verkauf", {}), reverse=True),
    }
