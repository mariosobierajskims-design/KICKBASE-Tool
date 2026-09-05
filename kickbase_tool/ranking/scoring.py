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
    "market_value": (lambda pm: pm.market_value, False),  # cheaper = better value for a buyer
    "points_per_value": (lambda pm: pm.points_per_market_value, True),
    "team_form": (lambda pm: pm.team_form, True),
    "opponent_form": (lambda pm: pm.opponent_form, False),  # weaker opponent = better for the player
    "table_position_diff": (lambda pm: pm.table_position_diff, True),
    "venue_form_diff": (lambda pm: pm.venue_form_diff, True),
    "start_rate": (lambda pm: pm.recent_form.start_rate, True),
    "remaining_schedule": (lambda pm: pm.remaining_schedule_difficulty, True),  # higher avg opponent position = weaker opponents = easier
}

AUFSTELLUNG_CATEGORIES = [
    "season_avg", "recent_avg", "recent_min", "recent_max", "recent_min_max_avg",
    "team_form", "opponent_form", "table_position_diff", "venue_form_diff",
    "goals_assists_cleansheets", "start_rate",
]
KAUF_CATEGORIES = AUFSTELLUNG_CATEGORIES + ["market_value", "points_per_value", "remaining_schedule"]
VERKAUF_CATEGORIES = KAUF_CATEGORIES


@dataclass
class RankingResult:
    scores: Dict[str, float]  # player_id -> final average rank (lower = better)
    category_ranks: Dict[str, Dict[str, float]]  # category -> player_id -> rank
    order: List[str]  # player ids sorted best-first


def load_weights(path: Path = DEFAULT_WEIGHTS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _combined_goals_assists_cleansheets_rank(metrics_by_id: Dict[str, PlayerMetrics]) -> Dict[str, float]:
    """Kennzahl 12 bundles three raw stats (Tore, Vorlagen, zu-Null) into a single
    rank category, as required ("15 Kennzahlen" total). Each raw stat is ranked
    across the player pool on its own (higher = better), then the three ranks
    are averaged into one composite value per player. That composite is itself
    already rank-like (lower = better), so it is exposed as a "lower is better"
    category to the generic ranking pipeline.
    """
    goals = {pid: pm.goals for pid, pm in metrics_by_id.items()}
    assists = {pid: pm.assists for pid, pm in metrics_by_id.items()}
    clean_sheets = {pid: pm.clean_sheets for pid, pm in metrics_by_id.items()}

    goal_ranks = rank_with_ties(goals, higher_is_better=True)
    assist_ranks = rank_with_ties(assists, higher_is_better=True)
    clean_sheet_ranks = rank_with_ties(clean_sheets, higher_is_better=True)

    return {
        pid: (goal_ranks[pid] + assist_ranks[pid] + clean_sheet_ranks[pid]) / 3
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
    weights = load_weights(weights_path)
    eligible = {pid: pm for pid, pm in metrics_by_id.items() if not pm.player.is_unavailable}
    return {
        "aufstellung": compute_ranking(eligible, AUFSTELLUNG_CATEGORIES, weights.get("aufstellung", {})),
        "kauf": compute_ranking(eligible, KAUF_CATEGORIES, weights.get("kauf", {})),
        "verkauf": compute_ranking(eligible, VERKAUF_CATEGORIES, weights.get("verkauf", {}), reverse=True),
    }
